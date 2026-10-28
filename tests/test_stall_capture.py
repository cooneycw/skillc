"""ci/stall_capture (#484): the stall monitor, driven only by replayed fixtures
and fake /proc trees. Nothing here samples, loads or touches a real host."""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from ci.stall_capture import attribute as at
from ci.stall_capture import guest, host, loop
from ci.stall_capture import procfs as pf

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "stall-capture"
PACKAGE = ROOT / "ci" / "stall_capture"

_spec = importlib.util.spec_from_file_location("make_fixtures", FIXTURES / "make_fixtures.py")
assert _spec and _spec.loader
mf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mf)


def _streams(scenario: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return (at.load(FIXTURES / f"{scenario}.guest.jsonl", "guest"),
            at.load(FIXTURES / f"{scenario}.host.jsonl", "host"))


def _report(scenario: str, with_host: bool = True) -> dict[str, Any]:
    g, h = _streams(scenario)
    return at.attribute(g, h if with_host else None, self_vm="vm-ci" if with_host else None)


# --- the fixtures ---------------------------------------------------------

@pytest.mark.parametrize("scenario", sorted(mf.SCENARIOS))
def test_the_committed_fixtures_are_what_the_generator_writes(scenario: str) -> None:
    for name, text in mf.render(scenario).items():
        assert (FIXTURES / name).read_text(encoding="utf-8") == text, f"{name} drifted; rerun make_fixtures.py"


def _names(record: dict[str, Any]) -> dict[str, set[str]]:
    """Every runtime-supplied name a sample record carries (C3)."""
    names: dict[str, set[str]] = {"device": set(), "vm": set(), "cgroup": set()}
    if "device" in record:
        names["device"].add(record["device"])
    names["device"] |= set(record.get("devices", {}))
    names["vm"] |= set(record.get("vms", {}))
    names["cgroup"] |= set(record.get("cgroups", {}))
    return names


def non_placeholder_names(record: dict[str, Any]) -> list[str]:
    return sorted(n for kind, found in _names(record).items() for n in found - mf.PLACEHOLDERS[kind])


def test_every_committed_fixture_names_only_placeholders() -> None:
    """C3: no host, VM or device name is committed. An allowlist, so this file
    itself never has to spell the names it keeps out."""
    files = sorted(FIXTURES.glob("*.jsonl"))
    assert len(files) == 2 * len(mf.SCENARIOS)
    for path in files:
        for record in at.load(path, path.name.split(".")[1]):
            assert non_placeholder_names(record) == [], path.name


def test_red_the_placeholder_guard_sees_a_real_looking_name() -> None:
    g, h = _streams("quiet")
    assert non_placeholder_names({**g[0], "device": "sda"}) == ["sda"]
    assert non_placeholder_names({**h[0], "vms": {**h[0]["vms"], "vm-123": {}}}) == ["vm-123"]


@pytest.mark.parametrize("argv", [
    (guest.main, ["--cgroup-root", "/x", "--duration", "10", "--out", "o"]),
    (guest.main, ["--device", "dev-g", "--duration", "10", "--out", "o"]),
    (host.main, ["--vm", "vm-ci=/x", "--duration", "10", "--out", "o"]),
    (host.main, ["--device", "dev-a", "--duration", "10", "--out", "o"]),
])
def test_names_are_runtime_arguments_with_no_default(argv: Any) -> None:
    main, args = argv
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2


# --- attribution ----------------------------------------------------------

@pytest.mark.parametrize("scenario", sorted(s for s, (_, _, v) in mf.SCENARIOS.items() if v))
def test_each_scenario_gets_its_verdict(scenario: str) -> None:
    report = _report(scenario)
    (stall,) = report["stalls"]
    assert stall["verdict"] == mf.SCENARIOS[scenario][2]
    assert (stall["start"], stall["end"], stall["ticks"]) == (mf.T0 + 50, mf.T0 + 70, 3)
    assert stall["unassessed"] == []


def test_the_cpu_burn_control_books_to_cpu_never_to_the_disk() -> None:
    """C1's control: a CPU burn has cpu pressure and quiet io, and must not be
    attributed to any io cause even though the host and disk keep working."""
    (stall,) = _report("cpuburn")["stalls"]
    assert stall["kind"] == ["cpu"] and stall["causes"] == ["contention"]
    assert not set(stall["causes"]) & set(at.IO_CAUSES)
    assert "discard_mbps_max" not in stall["evidence"]


def test_a_quiet_window_is_zero_stalls_and_says_what_it_covered() -> None:
    report = _report("quiet")
    assert report["stalls"] == [] and report["guest_samples"] == 12 and report["host_samples"] == 12
    assert at.headline(report).startswith("stall-capture: 0 stall window(s) in 12 guest sample(s) over 110.0 s")


def test_a_guest_only_verdict_names_what_nobody_looked_at() -> None:
    (stall,) = _report("discard", with_host=False)["stalls"]
    assert stall["verdict"] == "discard" and stall["unassessed"] == ["device", "neighbour"]


def test_the_mixed_window_is_ambiguous_not_the_first_cause_found() -> None:
    (stall,) = _report("mixed")["stalls"]
    assert stall["causes"] == ["discard", "device"] and stall["verdict"] == "ambiguous"


def test_an_io_stall_with_no_matching_rule_is_unattributed() -> None:
    g, h = _streams("device")
    (stall,) = at.attribute(g, h, self_vm="vm-ci", th=at.Thresholds(device_await_ms=1e9))["stalls"]
    assert stall["verdict"] == "UNATTRIBUTED" and stall["causes"] == []


def test_the_guest_vm_is_never_its_own_neighbour() -> None:
    g, h = _streams("neighbour")
    (stall,) = at.attribute(g, h, self_vm="vm-a")["stalls"]  # declaring the busy VM as self
    assert "neighbour" not in stall["causes"]


def _write(tmp_path: Path, name: str, records: list[dict[str, Any]]) -> Path:
    path = tmp_path / name
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


@pytest.mark.parametrize(("case", "match"), [
    ("empty", "0 usable sample"),
    ("one", "1 usable sample"),
    ("errors", r"1 usable sample\(s\) \(11 error record"),
    ("no-self", "needs --self-vm"),
    ("bad-self", "not a VM label"),
    ("no-overlap", "does not overlap"),
])
def test_red_nothing_to_look_at_is_refused_not_clean(tmp_path: Path, case: str, match: str) -> None:
    g, h = _streams("quiet")
    self_vm: str | None = "vm-ci"
    if case == "empty":
        g = []
    elif case == "one":
        g = g[:1]
    elif case == "errors":
        g = [g[0]] + [{"source": "guest", "t": r["t"], "error": "unreadable"} for r in g[1:]]
    elif case == "no-self":
        self_vm = None
    elif case == "bad-self":
        self_vm = "vm-zz"
    elif case == "no-overlap":
        h = [{**r, "t": r["t"] + 10_000} for r in h]
    with pytest.raises(at.Refused, match=match):
        at.attribute(g, h, self_vm=self_vm)


def test_the_cli_refuses_with_exit_2_and_reports_with_exit_0(tmp_path: Path, capsys: Any) -> None:
    empty = _write(tmp_path, "empty.jsonl", [])
    assert at.main(["--guest", str(empty)]) == 2
    assert "refused" in capsys.readouterr().err
    out = tmp_path / "report.json"
    assert at.main(["--guest", str(FIXTURES / "discard.guest.jsonl"), "--host", str(FIXTURES / "discard.host.jsonl"),
                    "--self-vm", "vm-ci", "--out", str(out)]) == 0
    assert json.loads(out.read_text())["verdicts"] == {"discard": 1}
    assert "1 stall window(s)" in capsys.readouterr().out


def test_a_stream_of_the_wrong_source_or_not_json_is_refused(tmp_path: Path) -> None:
    _, h = _streams("quiet")
    with pytest.raises(at.Refused, match="not 'guest'"):
        at.load(_write(tmp_path, "g.jsonl", h), "guest")
    (tmp_path / "bad.jsonl").write_text("{not json\n")
    with pytest.raises(at.Refused, match="not JSON"):
        at.load(tmp_path / "bad.jsonl", "guest")


# --- the samplers, against a fake tree -------------------------------------

def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    (root / "proc" / "pressure").mkdir(parents=True)
    for r, some in (("io", 12.5), ("cpu", 3.25), ("memory", 0.0)):
        (root / "proc" / "pressure" / r).write_text(
            f"some avg10={some} avg60=1.00 avg300=0.50 total=123\nfull avg10=1.50 avg60=0.00 avg300=0.00 total=9\n")
    cols = " ".join(str(n) for n in range(1, 18))  # 15 counters + flushes
    (root / "proc" / "diskstats").write_text(f" 252 0 dev-g {cols}\n 252 1 dev-a {cols}\n 7 0 loop0 1 2 3\n")
    (root / "proc" / "stat").write_text("cpu  100 1 50 1000 7 0 2 40 0 0\ncpu0 50 0 25 500 3 0 1 20 0 0\n")
    for cg in ("ctr-a", "ctr-b"):
        d = root / "sys" / "fs" / "cgroup" / "pipeline" / cg
        d.mkdir(parents=True)
        (d / "cpu.stat").write_text("usage_usec 900\nnr_periods 10\nnr_throttled 3\nthrottled_usec 4500\n")
        (d / "cpu.max").write_text("200000 100000\n")
        (d / "io.pressure").write_text("some avg10=7.00 avg60=0 avg300=0 total=1\nfull avg10=0 avg60=0 avg300=0 total=0\n")
    vm = root / "sys" / "fs" / "cgroup" / "vms" / "vm-ci"
    vm.mkdir(parents=True)
    (vm / "io.pressure").write_text("some avg10=4.00 avg60=0 avg300=0 total=1\n")
    (vm / "cpu.pressure").write_text("some avg10=2.00 avg60=0 avg300=0 total=1\n")
    (vm / "io.stat").write_text("252:0 rbytes=10 wbytes=20 rios=1 wios=2 dbytes=5 dios=1\n"
                                "252:1 rbytes=1 wbytes=2 rios=1 wios=1 dbytes=0 dios=0\n")
    return root


def test_the_guest_sampler_reads_the_fake_tree(tmp_path: Path) -> None:
    s = guest.sample(_tree(tmp_path), "dev-g", "/sys/fs/cgroup/pipeline")
    assert s["psi"]["io"] == {"some_avg10": 12.5, "full_avg10": 1.5} and s["psi"]["cpu"]["some_avg10"] == 3.25
    assert s["disk"]["discard_sectors"] == 14 and s["disk"]["write_sectors"] == 7
    assert s["cpu"] == {"total": 1200, "steal": 40, "iowait": 7}
    assert set(s["cgroups"]) == {"ctr-a", "ctr-b"}
    assert s["cgroups"]["ctr-a"] == {"nr_throttled": 3, "throttled_usec": 4500, "usage_usec": 900,
                                     "cpu_max": "200000 100000", "io_some_avg10": 7.0}


def test_the_host_sampler_reads_the_fake_tree(tmp_path: Path) -> None:
    s = host.sample(_tree(tmp_path), ["dev-a"], {"vm-ci": "/sys/fs/cgroup/vms/vm-ci"})
    assert s["devices"]["dev-a"]["discard_ms"] == 15
    assert s["vms"]["vm-ci"] == {"io_some_avg10": 4.0, "cpu_some_avg10": 2.0, "rbytes": 11, "wbytes": 22,
                                 "rios": 2, "wios": 3, "dbytes": 5, "dios": 1}


@pytest.mark.parametrize(("breakage", "match"), [
    ("device", r"no line .* for \['dev-zz'\]"),
    ("pressure", "/proc/pressure/io"),
    ("no-discard-columns", r"no line \(with discard columns\)"),
    ("pressure-garbled", "no 'some avg10'"),
])
def test_red_an_unreadable_interface_is_refused_not_zero(tmp_path: Path, breakage: str, match: str) -> None:
    root = _tree(tmp_path)
    device = "dev-g"
    if breakage == "device":
        device = "dev-zz"
    elif breakage == "pressure":
        (root / "proc" / "pressure" / "io").unlink()
    elif breakage == "pressure-garbled":
        (root / "proc" / "pressure" / "io").write_text("PSI unavailable\n")
    elif breakage == "no-discard-columns":  # a pre-4.18 kernel: 11 counters
        (root / "proc" / "diskstats").write_text(" 252 0 dev-g 1 2 3 4 5 6 7 8 9 10 11\n")
    with pytest.raises(pf.Unreadable, match=match):
        guest.sample(root, device, "/sys/fs/cgroup/pipeline")


def test_the_sampler_cli_refuses_before_the_loop(tmp_path: Path, capsys: Any) -> None:
    out = tmp_path / "g.jsonl"
    assert guest.main(["--device", "dev-zz", "--cgroup-root", "/sys/fs/cgroup/pipeline", "--duration", "10",
                       "--out", str(out), "--root", str(_tree(tmp_path))]) == 2
    assert not out.exists() and "refused" in capsys.readouterr().err
    assert host.main(["--device", "dev-a", "--vm", "bad-spec", "--duration", "10", "--out", str(out)]) == 2


def test_the_loop_records_a_gap_as_an_error_and_goes_on(tmp_path: Path) -> None:
    now = [0.0]
    answers = iter([{"x": 1}, None, {"x": 3}])

    def sample() -> dict[str, Any]:
        value = next(answers)
        if value is None:
            raise pf.Unreadable("gone")
        return value

    def sleep(seconds: float) -> None:
        now[0] += seconds
    out = tmp_path / "s.jsonl"
    ticks = loop.run(sample, source="guest", interval=10, duration=25, out=out, clock=lambda: now[0],
                     monotonic=lambda: now[0], sleep=sleep)
    records = [json.loads(line) for line in out.read_text().splitlines()]
    assert ticks == 3 and [r.get("x", r.get("error")) for r in records] == [1, "gone", 3]
    assert [r["t"] for r in records] == [0.0, 10.0, 20.0]


def test_red_no_sleep_reaches_past_the_deadline(tmp_path: Path) -> None:
    """An interval longer than the duration must not hold the loop open past it,
    and wall-clock jumps must not stretch the run: scheduling is monotonic."""
    mono, slept = [0.0], []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        mono[0] += seconds
    wall = iter(range(0, 10**9, 10**6))  # a wall clock leaping forward by days per read
    ticks = loop.run(dict, source="guest", interval=3600, duration=1, out=tmp_path / "s.jsonl",
                     clock=lambda: float(next(wall)), monotonic=lambda: mono[0], sleep=sleep)
    assert ticks == 1 and slept == [1.0] and mono[0] == 1.0


@pytest.mark.parametrize(("interval", "duration"), [(0.5, 10), (10, 0), (10, loop.MAX_DURATION_SECONDS + 1),
                                                    (float("inf"), 10), (float("nan"), 10)])
def test_red_an_unbounded_loop_is_refused(interval: float, duration: float) -> None:
    with pytest.raises(ValueError, match="must"):
        loop.check_bounds(interval, duration)


# --- read-only by construction ---------------------------------------------

def writes_in(source: str) -> list[str]:
    """Every call that could write a file or run a command: a Path mutator,
    anything on `subprocess` or `os` that runs or mutates, and an `open` whose
    mode writes."""
    tree = ast.parse(source)
    # `replace` is left out: on a str it is not a write, and str.replace is common.
    mutators = {"write_text", "write_bytes", "unlink", "mkdir", "rmdir", "rename", "chmod", "touch"}
    hits: list[str] = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
        owner = f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else ""
        if name in mutators or owner == "subprocess" or (owner == "os" and name not in ("getpid", "cpu_count")):
            hits.append(f"{owner}.{name}" if owner in ("subprocess", "os") else name)
        elif name == "open":
            mode = (n.args[1:2] or [kw.value for kw in n.keywords if kw.arg == "mode"]
                    or ([n.args[0]] if isinstance(f, ast.Attribute) and n.args else []))
            if mode and isinstance(mode[0], ast.Constant) and set(str(mode[0].value)) & set("wax+"):
                hits.append(f"open({mode[0].value!r})")
    return hits


def test_the_samplers_read_and_never_write() -> None:
    """Only `loop.run` opens anything for writing: its own output file."""
    for name in ("procfs.py", "guest.py", "host.py"):
        assert writes_in((PACKAGE / name).read_text(encoding="utf-8")) == [], name
    assert writes_in((PACKAGE / "attribute.py").read_text(encoding="utf-8")) == ["write_text"]  # its --out report
    assert writes_in((PACKAGE / "loop.py").read_text(encoding="utf-8")) == ["open('a')"]  # its own output


def test_red_the_write_detector_sees_a_write() -> None:
    assert writes_in("p.write_text('x')\nsubprocess.run(['x'])\nopen(p, 'w')\nos.remove(p)\nq.open(mode='a+')\n"
                     ) == ["write_text", "subprocess.run", "open('w')", "os.remove", "open('a+')"]
    assert writes_in("pf.read(root, '/proc/stat')\nloop.run(f)\nopen(p)\np.open('r')\n") == []


def test_red_discard_that_does_not_dominate_writes_is_not_the_cause() -> None:
    """The device scenario discards 0.5 MB/s under 20 MB/s of writes: past a
    floored threshold it is still not the cause, because writes outweigh it."""
    g, h = _streams("device")
    (stall,) = at.attribute(g, h, self_vm="vm-ci", th=at.Thresholds(discard_mbps=0.1))["stalls"]
    assert "discard" not in stall["causes"] and stall["verdict"] == "device"


# --- coverage is stated, never assumed (counter-model review) --------------

def test_red_a_stall_on_the_first_sample_is_detected() -> None:
    g, h = _streams("quiet")
    g[0]["psi"]["io"]["some_avg10"] = 90.0
    (stall,) = at.attribute(g, h, self_vm="vm-ci")["stalls"]
    assert stall["start"] == mf.T0 and stall["kind"] == ["io"]
    assert "discard" in stall["unassessed"]  # the first sample has no rate behind it


def test_red_no_container_observed_leaves_throttle_unassessed() -> None:
    g, _ = _streams("throttle")
    for record in g:
        record["cgroups"] = {}
    (stall,) = at.attribute(g)["stalls"]
    assert stall["verdict"] == "contention" and "throttle" in stall["unassessed"]
    assert "throttle_share_max" not in stall["evidence"]


def test_red_a_host_stream_with_no_other_vm_leaves_neighbour_unassessed() -> None:
    g, h = _streams("discard")
    for record in h:
        del record["vms"]["vm-a"]
    (stall,) = at.attribute(g, h, self_vm="vm-ci")["stalls"]
    assert stall["verdict"] == "discard" and stall["unassessed"] == ["neighbour"]
    assert "busy_neighbours" not in stall["evidence"]


def test_red_a_vm_cgroup_without_io_stat_is_recorded_absent_not_refused(tmp_path: Path) -> None:
    """A hypervisor that does not delegate the io controller to VM cgroups has
    io.pressure but no io.stat; the first live run was refused on exactly that."""
    root = _tree(tmp_path)
    (root / "sys" / "fs" / "cgroup" / "vms" / "vm-ci" / "io.stat").unlink()
    s = host.sample(root, ["dev-a"], {"vm-ci": "/sys/fs/cgroup/vms/vm-ci"})
    assert s["vms"]["vm-ci"] == {"io_some_avg10": 4.0, "cpu_some_avg10": 2.0, "io_stat": "absent"}


@pytest.mark.parametrize(("neighbour_psi", "busy"), [(60.0, ["vm-a"]), (1.0, [])])
def test_red_a_neighbour_without_io_stat_is_judged_on_pressure_and_its_rate_unassessed(
        neighbour_psi: float, busy: list[str]) -> None:
    g, h = _streams("discard")
    for record in h:
        vm_a = record["vms"]["vm-a"]
        for key in ("rbytes", "wbytes", "rios", "wios", "dbytes", "dios"):
            vm_a.pop(key, None)
        vm_a["io_stat"] = "absent"
        vm_a["io_some_avg10"] = neighbour_psi
    (stall,) = at.attribute(g, h, self_vm="vm-ci")["stalls"]
    assert stall["evidence"]["busy_neighbours"] == busy
    assert ("neighbour" in stall["causes"]) == bool(busy)
    assert "neighbour_rate" in stall["unassessed"] and "neighbour" not in stall["unassessed"]
    assert stall["evidence"]["neighbour_rate_unobserved"] == ["vm-a"]


def test_red_a_host_interval_overlapping_a_one_tick_stall_is_joined() -> None:
    """Guest stall on the tick ending at +50 (interval 40-50); the host interval
    43-53 overlaps it although it ends after the window."""
    g, h = _streams("quiet")
    g[5]["psi"]["io"]["some_avg10"] = 80.0
    dev = [r["devices"]["dev-a"] for r in h]
    for i in range(5, len(dev)):  # the host interval ending at +53 carries a 300 ms await
        dev[i]["write_ms"] += 300 * 1100
    (stall,) = at.attribute(g, h, self_vm="vm-ci")["stalls"]
    assert (stall["start"], stall["ticks"]) == (mf.T0 + 50, 1)
    assert stall["verdict"] == "device" and stall["evidence"]["host_intervals"]["partial"] >= 1


def test_red_a_missing_cgroup_root_is_refused(tmp_path: Path) -> None:
    with pytest.raises(pf.Unreadable, match="not a directory"):
        guest.sample(_tree(tmp_path), "dev-g", "/no/such/cgroup/root")


def test_red_a_host_interval_only_touching_the_window_is_not_joined() -> None:
    """A one-tick stall with no lead-in sample (the first one) ends at +0; a host
    interval (+0, +10] happened entirely after it and must not explain it."""
    g, h = _streams("quiet")
    g[0]["psi"]["io"]["some_avg10"] = 90.0
    for record in h:
        record["t"] -= 3  # host ticks on the guest's own timestamps
    for record in h[1:]:
        record["vms"]["vm-a"]["wbytes"] += int(500e6 * mf.TICK)
    (stall,) = at.attribute(g, h, self_vm="vm-ci")["stalls"]
    assert stall["end"] == mf.T0 and "neighbour" not in stall["causes"]


def test_red_a_write_burst_elsewhere_does_not_mask_dominant_discard() -> None:
    g, h = _streams("discard")
    for record in g[4:]:  # the lead-in interval (tick 4) also writes 2 GB/s
        record["disk"]["write_sectors"] += int(2000 * mf.TICK * mf.MB_SECTORS)
    (stall,) = at.attribute(g, h, self_vm="vm-ci")["stalls"]
    assert stall["verdict"] == "discard"


def test_red_error_records_split_a_window_and_rates() -> None:
    g, _ = _streams("quiet")
    for i in (4, 8):
        g[i]["psi"]["io"]["some_avg10"] = 90.0
    for i in (5, 6, 7):
        g[i] = {"source": "guest", "t": g[i]["t"], "error": "gone"}
    stalls = at.attribute(g)["stalls"]
    assert [(s["start"], s["ticks"]) for s in stalls] == [(mf.T0 + 40, 1), (mf.T0 + 80, 1)]
    assert "discard" in stalls[1]["unassessed"]  # no rate is bridged across the gap


@pytest.mark.parametrize("name", ["io_psi", "cpu_psi", "device_await_ms"])
def test_red_a_non_finite_threshold_is_refused(name: str, tmp_path: Path, capsys: Any) -> None:
    with pytest.raises(at.Refused, match="non-finite"):
        at.Thresholds(**{name: float("nan")})
    flag = "--" + name.replace("_", "-")
    assert at.main(["--guest", str(FIXTURES / "device.guest.jsonl"), flag, "nan"]) == 2
    assert "non-finite" in capsys.readouterr().err
