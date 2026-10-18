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
HOLDER_ENV = "SKILLC_FAILURE_CONTEXT_HOLDER"  # tests point it at a fixture file



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


def _cmdline(entry: Path) -> list[bytes]:
    return (entry / "cmdline").read_bytes().split(b"\0")


def _neighbours() -> dict[str, Any]:
    """Counts over THIS uid's processes only (a narrow, labelled census:
    other users' processes are out of scope), with how many could not be
    read, so an unreadable population is never reported as zero."""
    pytest_procs = xdist_workers = inspected = unreadable = 0
    me = os.getuid()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != me:
                continue
            argv = _cmdline(entry)
        except FileNotFoundError:
            continue  # exited while we looked
        except OSError:
            unreadable += 1
            continue
        inspected += 1
        if any(a.endswith(b"pytest") or a == b"pytest" for a in argv[:3]) or \
                b"pytest" in argv[1:3]:
            pytest_procs += 1
        if b"execnet" in b" ".join(argv) or any(b"xdist" in a for a in argv[:4]):
            xdist_workers += 1
    holder = _read(os.environ.get(HOLDER_ENV, str(LOCK_HOLDER))).strip()
    return {
        "census_scope": "same-uid",
        "census_inspected": inspected,
        "census_unreadable": unreadable,
        "census_partial": unreadable > 0,
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


# ------------------------------------------------------------------ the plugin

#: Outer sessions currently active in THIS process (an in-process inner
#: session, e.g. pytester's, starts while this is non-zero).
_active_outer = [0]


def _scrubber() -> Any:
    """Home and user name, captured now: the suite's autouse fixtures patch
    Path.home during every test, which is when reports are built."""
    home = str(Path.home())
    try:
        import pwd

        user = pwd.getpwuid(os.getuid()).pw_name
    except (ImportError, KeyError):
        user = os.path.basename(home)
    names = {n for n in (user, os.path.basename(home), os.environ.get("USER", "")) if len(n) >= 3}

    def scrub(value: Any) -> Any:
        if isinstance(value, str):
            value = value.replace(home, "~")
            for name in names:
                value = value.replace(name, "<user>")
            return value
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value

    return scrub


class FailureContext:
    """One instance per pytest session (config). Every hook checks ITS OWN
    session's flag, so a nested session can neither record, authorize its
    workers, nor print, whatever another session in this process is doing."""

    def __init__(self, config: pytest.Config) -> None:
        self.config = config
        self.enabled = False
        self.worker = getattr(config, "workerinput", None) is not None
        self.sampler: _Sampler | None = None
        self.sampler_error: str | None = None
        self.lines: list[str] = []
        self.scrub = _scrubber()
        report_dir = Path(os.environ.get("PYTEST_REPORT_DIR", "reports"))
        self.out = (report_dir if report_dir.is_absolute()
                    else Path(config.rootpath) / report_dir) / "failure-context.jsonl"

    def _nested(self) -> bool:
        workerinput = getattr(self.config, "workerinput", None)
        if workerinput is not None:
            return not workerinput.get(WORKER_FLAG)
        if _active_outer[0]:
            return True  # an in-process inner session while an outer one runs
        outer = os.environ.get(OUTER_ENV)
        return bool(outer) and outer != str(os.getpid())

    @pytest.hookimpl
    def pytest_configure(self, config: pytest.Config) -> None:
        if config is not self.config or os.environ.get(DISABLE_ENV) == "0" or self._nested():
            return
        self.enabled = True
        if not self.worker:
            _active_outer[0] += 1
            os.environ[OUTER_ENV] = str(os.getpid())
        try:
            self.sampler = _Sampler()
        except Exception as exc:  # noqa: BLE001 - capture continues without history
            self.sampler_error = f"unavailable: sampler did not start: {exc!r}"[:200]

    @pytest.hookimpl
    def pytest_unconfigure(self, config: pytest.Config) -> None:
        if config is not self.config or not self.enabled:
            return
        if self.sampler is not None:
            self.sampler.stop()
        if not self.worker:
            _active_outer[0] -= 1
            if os.environ.get(OUTER_ENV) == str(os.getpid()) and not _active_outer[0]:
                del os.environ[OUTER_ENV]

    @pytest.hookimpl(optionalhook=True)
    def pytest_configure_node(self, node: Any) -> None:
        """xdist controller: only an ENABLED session's workers record."""
        if self.enabled:
            node.workerinput[WORKER_FLAG] = True

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item: pytest.Item, call: Any):  # type: ignore[no-untyped-def]
        outcome = yield
        report = outcome.get_result()
        if not self.enabled or not report.failed:
            return
        record: dict[str, Any] = {"nodeid": report.nodeid, "when": report.when,
                                  "duration": round(report.duration, 3), "at": time.time()}
        for name, fn in (("now", _now), ("neighbours", _neighbours)):
            try:
                record[name] = fn()
            except Exception as exc:  # noqa: BLE001 - recorded, never raised
                record[name] = f"unavailable: {exc!r}"[:200]
        if self.sampler is not None:
            record["history"] = list(self.sampler.buffer)
            record["sampler_gaps"] = self.sampler.gaps
        else:
            record["history"] = self.sampler_error or "unavailable"
            record["sampler_gaps"] = None
        if _wants_docker(item):
            try:
                record["docker"] = _docker()
            except Exception as exc:  # noqa: BLE001
                record["docker"] = f"unavailable: {exc!r}"[:200]
        report.sections.append((SECTION, json.dumps(self.scrub(record), sort_keys=True)))

    @pytest.hookimpl
    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        """Controller side (or the only process without xdist): persist and summarise."""
        if not self.enabled or self.worker or not report.failed:
            return
        for name, content in report.sections:
            if name != SECTION:
                continue
            try:
                record = self.scrub(json.loads(content))
            except ValueError:
                continue
            self.lines.append(self.scrub(_summary_line(record)))
            try:
                self.out.parent.mkdir(parents=True, exist_ok=True)
                with self.out.open("a") as fh:
                    fh.write(json.dumps(record, sort_keys=True) + "\n")
            except OSError as exc:
                self.lines.append(self.scrub(f"FAILURE_CONTEXT: not written: {exc!r}"))

    @pytest.hookimpl
    def pytest_terminal_summary(self, terminalreporter: Any) -> None:
        if not self.enabled or not self.lines:
            return
        terminalreporter.section("failure context (#462)")
        for line in self.lines:
            terminalreporter.write_line(line)


def _wants_docker(item: pytest.Item) -> bool:
    if os.environ.get(DOCKER_ENV) == "1":
        return True
    return "docker" in item.nodeid.lower() or any(
        "docker" in m.name for m in item.iter_markers())


def _dict(value: Any) -> dict[str, Any]:
    """A section that was captured, or {} for one recorded `unavailable`."""
    return value if isinstance(value, dict) else {}


def _summary_line(record: dict[str, Any]) -> str:
    now, nb, dk = _dict(record.get("now")), _dict(record.get("neighbours")), _dict(record.get("docker"))
    cpu, io = _dict(now.get("psi_cpu")), _dict(now.get("psi_io"))
    load = now.get("loadavg") or [None]
    return (f"FAILURE_CONTEXT: {record['nodeid']} when={record.get('when')} load1={load[0]} "
            f"running={now.get('procs_running')} blocked={now.get('procs_blocked')} "
            f"psi_cpu10={cpu.get('some10')} psi_io10={io.get('some10')} "
            f"pytest_procs={nb.get('pytest_processes')} "
            f"docker_ps={dk.get('containers', '-')} kyle={dk.get('kyle_containers', '-')}")


def register(config: pytest.Config) -> None:
    """Called from tests/conftest.py: one plugin object for this session."""
    config.pluginmanager.register(FailureContext(config), "skillc-failure-context")
