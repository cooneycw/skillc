"""The #462 load harness: its own control, and its host-impact bounds.

The committed red is `test_spinners_disabled_reports_invalid`: the harness's
INVALID verdict is the only thing that separates "passed under load" from
"passed because no load was applied", so a run with the spinners disabled must
say INVALID and run nothing. The fake-/proc/stat pair shows the same verdict
logic turning on the sampled count alone, both ways.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ci import load_harness as lh

HARNESS = Path(lh.__file__)
PROC = Path("/proc/stat").is_file()
needs_proc = pytest.mark.skipif(not PROC, reason="needs Linux /proc")


def _fake_stat(tmp_path: Path, running: int) -> list[str]:
    stat = tmp_path / "stat"
    stat.write_text(f"cpu 1 2 3 4\nprocs_running {running}\nprocs_blocked 0\n")
    loadavg = tmp_path / "loadavg"
    loadavg.write_text("1.00 1.00 1.00 1/100 1\n")
    return ["--stat-path", str(stat), "--loadavg-path", str(loadavg)]


def _phase(tmp_path: Path, *opts: str, cmd: tuple[str, ...] = ()) -> tuple[int, dict, str]:
    out = tmp_path / "phase.json"
    proc = subprocess.run(
        [sys.executable, str(HARNESS), "phase", *opts, "--out", str(out), "--",
         *(cmd or (sys.executable, "-c", "pass"))],
        capture_output=True, text=True, timeout=90, check=False,
    )
    record = json.loads(out.read_text()) if out.exists() else {}
    return proc.returncode, record, proc.stderr


def _group_members(pgid: int) -> list[int]:
    members = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:
            continue
        # Field 5 (pgrp) follows the parenthesised comm, which may hold spaces.
        if int(stat.rsplit(")", 1)[1].split()[2]) == pgid:
            members.append(int(entry.name))
    return members


def _wait_gone(pgid: int, seconds: float = 5.0) -> list[int]:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        members = _group_members(pgid)
        if not members:
            return []
        time.sleep(0.1)
    return _group_members(pgid)


@needs_proc
def test_spinners_disabled_reports_invalid(tmp_path):
    """The committed red: no spinners, a target only load can reach -> INVALID."""
    target = 4 * (os.cpu_count() or 1) + 64
    rc, record, err = _phase(tmp_path, "--cpu", "0", "--churn", "0",
                             "--target", str(target), "--reps", "3",
                             "--warmup-seconds", "6")
    assert rc == 1, err
    assert record["verdict"] == "INVALID"
    assert record["warmup_reached"] is False
    assert record["reps"] == [], "an INVALID warm-up must run no reps"
    assert "LOAD_PHASE: INVALID" in err


def test_no_samples_is_invalid_never_a_division():
    assert lh.load_verdict([], 1) == ("INVALID", 0.0)


def test_sampled_count_below_target_is_invalid(tmp_path):
    rc, record, _ = _phase(tmp_path, "--cpu", "0", "--target", "50", "--reps", "2",
                           "--warmup-seconds", "6", *_fake_stat(tmp_path, 3))
    assert (rc, record["verdict"], record["reps"]) == (1, "INVALID", [])


def test_sampled_count_at_target_is_valid_and_runs_the_reps(tmp_path):
    rc, record, err = _phase(tmp_path, "--cpu", "0", "--target", "50", "--reps", "2",
                             "--warmup-seconds", "10", *_fake_stat(tmp_path, 50))
    assert rc == 0, err
    assert record["verdict"] == "VALID"
    assert [r["outcome"] for r in record["reps"]] == ["passed", "passed"]
    assert record["uptime_before"] and record["uptime_after"]


def test_a_failing_rep_is_recorded_with_its_output(tmp_path):
    rc, record, _ = _phase(
        tmp_path, "--cpu", "0", "--target", "1", "--reps", "1", "--warmup-seconds", "10",
        *_fake_stat(tmp_path, 5),
        cmd=(sys.executable, "-c", "import sys; print('boom-462'); sys.exit(3)"),
    )
    assert rc == 0
    (rep,) = record["reps"]
    assert (rep["outcome"], rep["exit"]) == ("failed", 3)
    assert "boom-462" in rep["tail"]


def test_a_rep_running_at_the_cap_is_truncated_not_counted(tmp_path):
    rc, record, _ = _phase(
        tmp_path, "--cpu", "0", "--target", "1", "--reps", "3", "--warmup-seconds", "10",
        "--max-seconds", "8", *_fake_stat(tmp_path, 5),
        cmd=(sys.executable, "-c", "import time; time.sleep(60)"),
    )
    assert rc == 0
    assert [r["outcome"] for r in record["reps"]] == ["truncated"]
    assert record["ended_at"] - record["started_at"] < 30


def test_a_phase_over_the_cap_is_refused(tmp_path):
    rc, record, err = _phase(tmp_path, "--cpu", "1", "--target", "1", "--reps", "1",
                             "--max-seconds", str(lh.PHASE_CAP_SECONDS + 1))
    assert rc == 2 and record == {}
    assert "phase cap" in err


@needs_proc
def test_the_load_is_real_and_gone_after_the_phase(tmp_path):
    """Spinners exist during a rep and their whole group is dead afterwards."""
    probe = tmp_path / "members"
    rep = (
        "import os, pathlib, sys\n"
        f"sys.path.insert(0, {str(Path(__file__).parent)!r})\n"
        "from test_load_harness import _group_members\n"
        "g = int(os.environ['SKILLC_LOAD_PGID'])\n"
        f"pathlib.Path({str(probe)!r}).write_text(str(len(_group_members(g))))\n"
    )
    # In-process, so the parent stays alive: the supervisor's parent-death
    # backstop cannot stand in for the harness's own stop.
    out = tmp_path / "phase.json"
    rc = lh.main(["phase", "--cpu", "2", "--target", "1", "--reps", "1",
                  "--warmup-seconds", "10", "--out", str(out), "--",
                  sys.executable, "-c", rep])
    record = json.loads(out.read_text())
    assert rc == 0
    assert int(probe.read_text()) >= 3, "supervisor + 2 spinners were not running"
    assert record["load_pgid"]
    assert _group_members(record["load_pgid"]) == [], "the load outlived its phase"


def _rep_marker(tmp_path: Path) -> str:
    return f"rep-462-{tmp_path.name}"


def _reps_alive(marker: str) -> list[int]:
    alive = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                if marker.encode() in (entry / "cmdline").read_bytes():
                    alive.append(int(entry.name))
            except OSError:
                continue
    return alive


def _start_phase(tmp_path: Path) -> tuple[subprocess.Popen[str], int]:
    marker = _rep_marker(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, str(HARNESS), "phase", "--cpu", "2", "--target", "1",
         "--reps", "1", "--warmup-seconds", "10", "--out", str(tmp_path / "p.json"),
         "--", sys.executable, "-c", f"import time; time.sleep(60); {marker!r}"],
        stderr=subprocess.PIPE, text=True,
    )
    assert proc.stderr is not None
    for line in proc.stderr:
        if line.startswith("LOAD_PGID: "):
            pgid = int(line.split()[1])
            break
    else:  # pragma: no cover - the harness always announces its group
        pytest.fail("no LOAD_PGID line")
    # The harness's own argv carries the marker too; wait for a process that is not it.
    while len(_group_members(pgid)) < 3 or not set(_reps_alive(marker)) - {proc.pid}:
        time.sleep(0.05)
    return proc, pgid


@needs_proc
def test_sigterm_kills_the_load_group_and_the_running_rep(tmp_path):
    proc, pgid = _start_phase(tmp_path)
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=10)
    assert _wait_gone(pgid, 2.0) == []
    assert _reps_alive(_rep_marker(tmp_path)) == [], "the running rep outlived the harness"


@needs_proc
def test_a_sigkilled_harness_still_takes_its_load_down(tmp_path):
    """The supervisor sees its parent change and kills its own group."""
    proc, pgid = _start_phase(tmp_path)
    proc.kill()
    proc.wait(timeout=10)
    assert _wait_gone(pgid, 5.0) == []


def _write_phase(path: Path, start: float, end: float, verdict: str,
                 outcomes: list[str], target: float = 48, nproc: int = 24) -> str:
    path.write_text(json.dumps({
        "started_at": start, "ended_at": end, "verdict": verdict,
        "target": target, "nproc": nproc,
        "reps": [{"outcome": o, "seconds": 1.0} for o in outcomes],
    }))
    return str(path)


def test_summarize_counts_only_valid_untruncated_reps(tmp_path):
    a = _write_phase(tmp_path / "a.json", 0, 100, "VALID", ["passed", "failed", "truncated"])
    b = _write_phase(tmp_path / "b.json", 300, 400, "INVALID", ["failed", "failed"])
    out = tmp_path / "m.json"
    assert lh.main(["summarize", "--member", "m", "--test-id", "t", "--label", "pre",
                    "--out", str(out), a, b]) == 0
    m = json.loads(out.read_text())
    assert (m["counted_reps"], m["failed"], m["truncated"]) == (2, 1, 1)
    assert m["invalid_phases"] == 1
    assert m["pauses_ok"] is True


def test_summarize_claims_2x_nproc_only_when_every_valid_phase_held_it(tmp_path):
    a = _write_phase(tmp_path / "a.json", 0, 100, "VALID", ["passed"], target=48)
    b = _write_phase(tmp_path / "b.json", 300, 400, "VALID", ["passed"], target=47)
    for phases, expected in (([a], True), ([a, b], False)):
        out = tmp_path / "m.json"
        lh.main(["summarize", "--member", "m", "--test-id", "t", "--label", "pre",
                 "--out", str(out), *phases])
        assert json.loads(out.read_text())["meets_2x_nproc"] is expected


def test_a_zero_target_is_refused(tmp_path):
    rc, record, err = _phase(tmp_path, "--cpu", "0", "--target", "0", "--reps", "1")
    assert rc == 2 and record == {}
    assert "vacuous" in err


def test_summarize_flags_a_short_pause(tmp_path):
    a = _write_phase(tmp_path / "a.json", 0, 100, "VALID", ["passed"])
    b = _write_phase(tmp_path / "b.json", 100 + lh.MIN_PAUSE_SECONDS - 1, 300, "VALID",
                     ["passed"])
    out = tmp_path / "m.json"
    lh.main(["summarize", "--member", "m", "--test-id", "t", "--label", "pre",
             "--out", str(out), a, b])
    assert json.loads(out.read_text())["pauses_ok"] is False


@pytest.mark.parametrize(("p", "reps"), [(0.5, 20), (0.1, 44), (0.05, 90), (1.0, 20)])
def test_reps_for_a_one_percent_chance_of_a_lucky_zero(p, reps):
    assert lh.reps_needed(p) == reps
    if p < 1:
        assert (1 - p) ** reps < 0.01


def test_the_driver_refuses_a_pause_under_the_floor(tmp_path):
    driver = HARNESS.parent / "load-repro.sh"
    proc = subprocess.run(
        [str(driver), "m", "tests/x.py", "1", "pre", "0"],
        capture_output=True, text=True, timeout=30, check=False,
        env=dict(os.environ, LOAD_PAUSE_SECONDS=str(lh.MIN_PAUSE_SECONDS - 1)),
    )
    assert proc.returncode == 2
    assert "floor" in proc.stderr


def test_scrub_removes_the_root_the_home_and_the_user(monkeypatch, tmp_path):
    home = tmp_path / "someuser"
    root = home / "Projects" / "skillc"
    root.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)  # conftest pins Path.home
    monkeypatch.chdir(root)
    text = (f"{root}/.venv/bin/python {home}/x "
            "/tmp/pytest-of-someuser/pytest-1/t0")
    out = lh.scrub(text)
    assert out == "<root>/.venv/bin/python ~/x /tmp/pytest-of-<user>/pytest-1/t0"
    assert "someuser" not in out


# ------------------------------------------------- Hold B: pinning and churn

_FAKE_DOCKER = r'''#!/usr/bin/env python3
"""A fake docker for the churn tests: `run` leaves a labelled container behind
(as a killed client can), `ps -aq --filter label=X` lists them, `rm -f` removes."""
import json, os, sys, time
state = os.environ["FAKE_DOCKER_STATE"]
def load():
    try:
        return json.load(open(state))
    except (OSError, ValueError):
        return {}
def save(d):
    tmp = state + f".{os.getpid()}"
    json.dump(d, open(tmp, "w"))
    os.replace(tmp, state)
args = sys.argv[1:]
d = load()
mode = os.environ.get("FAKE_DOCKER_MODE", "")
if args[0] == "run":
    label = args[args.index("--label") + 1]
    if mode == "delayed-create":
        # The daemon has accepted a create the client will not see finish:
        # it becomes visible only after the sweep's SECOND empty listing
        # (an event, not a clock, so the test means the same under any load).
        d.setdefault("_pending", {})[f"late{os.getpid()}"] = label
        save(d)
        sys.exit(0)
    d[f"c{os.getpid()}-{time.time_ns()}"] = label
    save(d)
    time.sleep(0.2)
elif args[0] == "ps" and mode == "ps-fails":
    sys.exit(1)
elif args[0] == "ps" and mode == "ps-hangs":
    time.sleep(3600)
elif args[0] == "ps":
    want = args[args.index("--filter") + 1].removeprefix("label=")
    print("\n".join(c for c, label in d.items()
                    if not c.startswith("_") and label == want))
    d["_ps"] = d.get("_ps", 0) + 1
    if d["_ps"] == 2:
        d.update(d.pop("_pending", {}))
    save(d)
elif args[0] == "rm":
    for c in args[2:]:
        d.pop(c, None)
    save(d)
'''


def _fake_docker(tmp_path: Path, monkeypatch) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    docker = bindir / "docker"
    docker.write_text(_FAKE_DOCKER.replace("/usr/bin/env python3", sys.executable))
    docker.chmod(0o755)
    state = tmp_path / "docker-state.json"
    state.write_text(json.dumps({"foreign": "skillc.load462=someone-else"}))
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(state))
    return state


def _containers(state: Path) -> dict[str, str]:
    """The fake daemon's containers, without its bookkeeping keys."""
    return {k: v for k, v in json.loads(state.read_text()).items() if not k.startswith("_")}


def test_docker_churn_removes_exactly_its_own_labelled_containers(tmp_path, monkeypatch):
    state = _fake_docker(tmp_path, monkeypatch)
    load = lh.Load(0, 0, time.time() + 60, docker=2)
    try:
        deadline = time.monotonic() + 20
        while len(json.loads(state.read_text())) < 3 and time.monotonic() < deadline:
            time.sleep(0.1)
        assert any(v == load.cfg["label"] for v in json.loads(state.read_text()).values())
    finally:
        load.stop()
    assert _containers(state) == {"foreign": "skillc.load462=someone-else"}


def test_io_churn_writes_inside_its_directory_and_removes_it(tmp_path):
    load = lh.Load(0, 0, time.time() + 60, io=1)
    iodir = Path(load.cfg["iodir"])
    try:
        deadline = time.monotonic() + 20
        seen = False
        while not seen and time.monotonic() < deadline:
            seen = any(iodir.iterdir()) if iodir.exists() else False
            time.sleep(0.01)
        assert seen, "the I/O churner never wrote"
    finally:
        load.stop()
    assert not iodir.exists()


def test_the_supervisor_cleans_up_when_its_deadline_passes(tmp_path, monkeypatch):
    """No stop() call: the supervisor's own backstop must remove the
    containers and the I/O directory, not only kill its group."""
    state = _fake_docker(tmp_path, monkeypatch)
    load = lh.Load(0, 0, time.time() + 2, docker=1, io=1)
    iodir = Path(load.cfg["iodir"])
    assert load.proc is not None
    load.proc.wait(timeout=30)
    assert _containers(state) == {"foreign": "skillc.load462=someone-else"}
    assert not iodir.exists()
    load.proc = None


def test_read_cpu_times_sums_only_the_pinned_cores(tmp_path):
    stat = tmp_path / "stat"
    stat.write_text(
        "cpu 99 0 0 99 0 0 0 0\n"
        "cpu0 10 0 0 90 0 0 0 0\n"
        "cpu1 50 0 0 40 10 0 0 0\n"
        "cpu2 100 0 0 0 0 0 0 0\n"
    )
    assert lh.read_cpu_times(stat, {0, 1}) == (60, 200)
    assert lh.parse_cpus("0-1,4") == {0, 1, 4}
    assert lh.busy_verdict([], 0.9) == (False, 0.0)
    # Summed, not averaged: 1 of 2 jiffies then 99 of 100 is 100/102 busy.
    assert lh.busy_verdict([(1, 2), (99, 100)], 0.9) == (True, 100 / 102)
    assert lh.busy_verdict([(80, 100), (5, 100)], 0.9)[0] is False


def _one_core() -> str:
    return str(max(os.sched_getaffinity(0)))


@needs_proc
def test_a_pinned_core_without_a_spinner_is_invalid(tmp_path):
    """The pinned control's red: the host-wide runnable count is met (target
    1), but the pinned core is not busy, so the phase must not count."""
    rc, record, err = _phase(tmp_path, "--cpu", "0", "--target", "1", "--reps", "1",
                             "--cpus", _one_core(), "--warmup-seconds", "8")
    assert rc == 1, err
    assert record["verdict"] == "INVALID" and record["reps"] == []


@needs_proc
def test_a_pinned_core_with_a_spinner_is_valid(tmp_path):
    rc, record, err = _phase(tmp_path, "--cpu", "1", "--target", "1", "--reps", "1",
                             "--cpus", _one_core(), "--warmup-seconds", "15")
    assert rc == 0, err
    assert record["verdict"] == "VALID"
    assert record["pinned_busy_mean"] >= 0.9


# ------------------------------------------------- review pass 1 (#462)

def _marker_alive(marker: str) -> list[int]:
    return _reps_alive(marker)


@needs_proc
def test_a_sigkilled_harness_does_not_leave_its_running_rep(tmp_path):
    proc, _pgid = _start_phase(tmp_path)
    proc.kill()
    proc.wait(timeout=10)
    deadline = time.monotonic() + 5
    while _marker_alive(_rep_marker(tmp_path)) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert _marker_alive(_rep_marker(tmp_path)) == [], "the rep outlived a SIGKILLed harness"


@needs_proc
def test_a_rep_that_exits_leaves_no_descendant_behind(tmp_path):
    marker = f"desc-462-{tmp_path.name}"
    child = f'import time; time.sleep(30); "{marker}"'
    rc, _record, err = _phase(
        tmp_path, "--cpu", "0", "--target", "1", "--reps", "1", "--warmup-seconds", "10",
        *_fake_stat(tmp_path, 5),
        cmd=("sh", "-c", f"({sys.executable} -c '{child}' >/dev/null 2>&1 &); exit 0"),
    )
    assert rc == 0, err
    assert _marker_alive(marker) == [], "a descendant of a finished rep is still running"


def test_a_sampler_failure_invalidates_the_phase(tmp_path):
    opts = _fake_stat(tmp_path, 50)
    stat = Path(opts[1])
    rc, record, err = _phase(
        tmp_path, "--cpu", "0", "--target", "50", "--reps", "1", "--warmup-seconds", "10",
        *opts,
        cmd=(sys.executable, "-c", f"import os, time; os.remove({str(stat)!r}); time.sleep(3)"),
    )
    assert rc == 1, err
    assert record["verdict"] == "INVALID"
    assert "sampler_error" in record


@needs_proc
def test_sleeping_workers_are_not_load(tmp_path):
    """The attributable control: the same group, the same membership, but the
    workers sleep. The host-wide count is met (target 1); the load's own CPU
    time is not, so the phase must not count."""
    rc, record, err = _phase(tmp_path, "--cpu", "2", "--spin-mode", "sleep", "--target", "1",
                             "--reps", "1", "--warmup-seconds", "8")
    assert rc == 1, err
    assert record["verdict"] == "INVALID"


@needs_proc
def test_busy_workers_are_attributed_their_cpu_time(tmp_path):
    rc, record, err = _phase(tmp_path, "--cpu", "2", "--target", "1", "--reps", "1",
                             "--warmup-seconds", "15",
                             cmd=(sys.executable, "-c", "import time; time.sleep(2)"))
    assert rc == 0, err
    assert record["load_cpu_share"] >= lh.MIN_LOAD_CPU_SHARE


def test_warm_up_never_outlasts_the_phase_cap(tmp_path):
    t0 = time.monotonic()
    rc, record, _ = _phase(tmp_path, "--cpu", "0", "--target", "50", "--reps", "1",
                           "--max-seconds", "3", "--warmup-seconds", "60",
                           *_fake_stat(tmp_path, 1))
    assert rc == 1 and record["verdict"] == "INVALID"
    assert time.monotonic() - t0 < 20


def test_summarize_holds_phases_to_the_load_cap(tmp_path):
    a = _write_phase(tmp_path / "a.json", 0, lh.PHASE_CAP_SECONDS + 50, "VALID", ["passed"])
    out = tmp_path / "m.json"
    lh.main(["summarize", "--member", "m", "--test-id", "t", "--label", "pre",
             "--out", str(out), a])
    assert json.loads(out.read_text())["phases_within_cap"] is False


def test_summarize_with_nothing_counted_fails_and_claims_nothing(tmp_path):
    a = _write_phase(tmp_path / "a.json", 0, 100, "INVALID", ["passed"])
    b = _write_phase(tmp_path / "b.json", 300, 400, "VALID", [])
    out = tmp_path / "m.json"
    rc = lh.main(["summarize", "--member", "m", "--test-id", "t", "--label", "pre",
                  "--out", str(out), a, b])
    m = json.loads(out.read_text())
    assert rc != 0, "an empty measured population must not exit 0"
    assert m["counted_reps"] == 0
    assert m["meets_2x_nproc"] is False



# ------------------------------------------------- review pass 2 (#462)

def test_a_failing_docker_listing_is_a_cleanup_failure_not_an_empty_one(tmp_path, monkeypatch):
    _fake_docker(tmp_path, monkeypatch)
    load = lh.Load(0, 0, time.time() + 60, docker=1)
    time.sleep(0.5)
    monkeypatch.setenv("FAKE_DOCKER_MODE", "ps-fails")
    load.stop()
    assert load.cleanup_error, "a failed `docker ps` was read as no containers"


def test_a_hanging_docker_listing_is_bounded(tmp_path, monkeypatch):
    _fake_docker(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_MODE", "ps-hangs")
    load = lh.Load(0, 0, time.time() + 60, docker=1, docker_timeout=1.0)
    t0 = time.monotonic()
    load.stop()
    assert time.monotonic() - t0 < 30
    assert load.cleanup_error


def test_a_container_created_after_the_client_died_is_still_removed(tmp_path, monkeypatch):
    state = _fake_docker(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_MODE", "delayed-create")
    load = lh.Load(0, 0, time.time() + 60, docker=1)
    deadline = time.monotonic() + 20
    while "_pending" not in json.loads(state.read_text()) and time.monotonic() < deadline:
        time.sleep(0.05)
    load.stop()
    final = json.loads(state.read_text())
    assert final.get("_ps", 0) >= 2, "the sweep never listed past the late create"
    assert "_pending" not in final
    assert _containers(state) == {"foreign": "skillc.load462=someone-else"}


@needs_proc
def test_a_rep_descendant_in_its_own_session_does_not_outlive_the_rep(tmp_path):
    """`FakeBackend.execute()` starts its client with start_new_session=True,
    so a rep's descendant can leave the rep's process group. With two reps,
    the second one looks for the first one's descendant: it must already be
    gone when the NEXT rep starts, not only when the phase ends."""
    marker = f"detached-462-{tmp_path.name}"
    seen = tmp_path / "seen-by-rep-2"
    # The marker is assembled at run time, so only the detached child's argv
    # carries it whole (the reps' own argv hold its two halves).
    head, tail = marker[:8], marker[8:]
    script = f"""
import pathlib, subprocess, sys
mark = {head!r} + {tail!r}
seen = pathlib.Path({str(seen)!r})
if seen.with_suffix(".rep1").exists():
    alive = []
    for e in pathlib.Path("/proc").iterdir():
        if e.name.isdigit():
            try:
                if mark.encode() in (e / "cmdline").read_bytes():
                    alive.append(e.name)
            except OSError:
                pass
    seen.write_text(str(len(alive)))
else:
    seen.with_suffix(".rep1").write_text("")
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30); " + repr(mark)],
                     start_new_session=True, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
"""
    rc, _record, err = _phase(
        tmp_path, "--cpu", "1", "--target", "1", "--reps", "2", "--warmup-seconds", "15",
        cmd=(sys.executable, "-c", script),
    )
    assert rc == 0, err
    assert seen.read_text() == "0", "the first rep's detached descendant was alive at rep 2"
    assert _marker_alive(marker) == []


@needs_proc
def test_the_rep_is_registered_before_its_command_runs(tmp_path):
    probe = tmp_path / "seen"
    script = ("import os, pathlib; "
              "f = pathlib.Path(os.environ['SKILLC_LOAD462_REP_FILE']).read_text(); "
              f"pathlib.Path({str(probe)!r}).write_text(f + ' ' + str(os.getpgid(0)))")
    rc, _record, err = _phase(tmp_path, "--cpu", "1", "--target", "1", "--reps", "1",
                              "--warmup-seconds", "15", cmd=(sys.executable, "-c", script))
    assert rc == 0, err
    registered, own = probe.read_text().split()
    assert registered == own


@needs_proc
def test_no_spinners_is_invalid_even_when_the_host_count_qualifies(tmp_path):
    rc, record, err = _phase(tmp_path, "--cpu", "0", "--target", "1", "--reps", "1",
                             "--warmup-seconds", "8")
    assert rc == 1, err
    assert record["verdict"] == "INVALID" and record["reps"] == []


def test_a_window_shorter_than_the_minimum_is_invalid(tmp_path):
    rc, record, err = _phase(tmp_path, "--cpu", "0", "--target", "1", "--reps", "1",
                             "--max-seconds", "6", "--warmup-seconds", "10",
                             *_fake_stat(tmp_path, 5))
    assert rc == 1, err
    assert record["verdict"] == "INVALID"
