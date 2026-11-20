"""Self-test for the run-window probes (#797 section 7, owner Q3).

The probes in `controls/run-window-probes/` run on the runner VM, some as root
and some against Docker. CI can run neither. What CI CAN qualify is each
probe's verdict logic: every script has a pure `--classify READINGS` mode that
applies the same classifier the live run uses, over committed readings.

The cases here are:
- syntax: every script parses under `sh -n`;
- fixtures: each committed readings file classifies to exactly its committed
  expectation, including the exit status (0 QUALIFIED, 1 MISMATCH);
- coverage: every probe has a qualified fixture whose fault arm is
  OBSERVATION_FAILED, plus at least one failing fixture;
- pairing: every readings file has exactly one expectation and vice versa;
- blind twins: each deliberately weakened copy of a classifier must still
  produce valid output but NOT reproduce the committed verdicts on its
  discriminating fixture, so the fixtures can tell a working classifier from a
  blind one;
- usage refusals: unknown flags and unreadable readings exit 2.

No live arm is run here, and nothing needs root, Docker or a VM.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PROBES = ROOT / "controls" / "run-window-probes"
FIXTURES = PROBES / "fixtures"
NAMES = [f"p{n}" for n in range(1, 9)]
VERDICTS = {"CONFIRMED_NEGATIVE", "SURVIVOR_OBSERVED", "OBSERVATION_FAILED"}

needs_sh = pytest.mark.skipif(shutil.which("sh") is None or shutil.which("awk") is None,
                              reason="sh and awk are required")


def classify(script: Path, readings: Path,
             lib: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
    if lib is not None:
        env["PROBE_LIB"] = str(lib)
    return subprocess.run(["sh", str(script), "--classify", str(readings)], capture_output=True,
                          text=True, env=env, check=False, timeout=30)


def fixture_cases() -> list[tuple[str, str]]:
    return sorted((p.parent.name, p.stem) for p in FIXTURES.glob("p*/*.readings"))


@needs_sh
@pytest.mark.parametrize("name", ["lib", *NAMES])
def test_every_probe_script_parses(name: str) -> None:
    run = subprocess.run(["sh", "-n", str(PROBES / f"{name}.sh")], capture_output=True,
                         text=True, check=False, timeout=30)
    assert run.returncode == 0, run.stderr


@needs_sh
@pytest.mark.parametrize(("probe", "case"), fixture_cases())
def test_fixture_classifies_to_its_committed_expectation(probe: str, case: str) -> None:
    expect = (FIXTURES / probe / f"{case}.expect").read_text()
    run = classify(PROBES / f"{probe}.sh", FIXTURES / probe / f"{case}.readings")
    assert run.stdout == expect
    arm_verdicts(run, probe)


@pytest.mark.parametrize("probe", NAMES)
def test_fixture_files_pair_exactly(probe: str) -> None:
    readings = {p.stem for p in (FIXTURES / probe).glob("*.readings")}
    expects = {p.stem for p in (FIXTURES / probe).glob("*.expect")}
    others = {p.name for p in (FIXTURES / probe).iterdir()} - {
        f"{n}{ext}" for n in readings for ext in (".readings", ".expect")}
    assert readings and readings == expects and not others


@pytest.mark.parametrize("probe", NAMES)
def test_every_probe_has_a_qualified_fault_arm_and_a_red_case(probe: str) -> None:
    qualified = (FIXTURES / probe / "qualified.expect").read_text()
    assert "ARM fault OBSERVATION_FAILED" in qualified
    assert qualified.rstrip().endswith(f"PROBE {probe} QUALIFIED")
    reds = [p for p in (FIXTURES / probe).glob("*.expect") if p.stem != "qualified"]
    assert reds and all(p.read_text().rstrip().endswith("MISMATCH") for p in reds)


#: (blind copy name, file to mutate, exact original text, weakened text, probe,
#: fixture, the arm whose verdict the weakening must change on that fixture)
BLIND_TWINS = [
    ("missing-is-zero", "lib.sh", 'if (n != 1 || bad || v == "" || v == "ERR") exit 1',
     'if (n != 1 || bad || v == "" || v == "ERR") v = 0', probe, "qualified", "fault")
    for probe in ("p1", "p4", "p5", "p7", "p8")
] + [
    ("trailing-garbage-accepted", "lib.sh",
     "$1 == a && $2 == k { n++; if (NF != 3) bad = 1; v = $3 }",
     "$1 == a && $2 == k { n++; v = $3 }", "p1", "trailing-garbage", "last"),
    ("unreadable-ignored", "p2.sh", '[ "$u" -eq 0 ] || return 1', ":", "p2", "qualified",
     "fault"),
    ("mmap-fd-trusted", "p2.sh", 'if [ "${h% *}" -ne 0 ]; then printf', "if false; then printf",
     "p2", "mmap-holder-kept-fd", "mmap"),
    ("unreadable-ignored", "p3.sh", 'if [ "$e" -ne 0 ] || [ "$u" -ne 0 ]; then',
     'if [ "$e" -ne 0 ]; then', "p3", "qualified", "fault"),
    ("lazy-listing-ignored", "p3.sh", '"$PROBE_NEG") if [ "$r" -eq 1 ]',
     '"$PROBE_NEG" | "$PROBE_SURV") if [ "$r" -eq 1 ]', "p3", "lazy-still-listed", "lazy"),
    ("late-reading-ignored", "p6.sh", 'a=$(rd_uint "$1" after_late)', 'a=$(rd_uint "$1" after)',
     "p6", "gc-late-kept-gone", "removed"),
    ("failed-rm-trusted", "p6.sh", 'if [ "$ok" -ne 1 ] || [ "$b" -lt 1 ]', "if false",
     "p6", "rm-failed", "removed"),
    ("unlanded-write-trusted", "p5.sh", 'if [ "$p" -eq 1 ]; then printf', "if true; then printf",
     "p5", "write-never-landed", "clean"),
    ("file-bind-unchecked", "p7.sh", 'if [ "$d" -eq 1 ] && [ "$f" -eq 1 ]; then',
     'if [ "$d" -eq 1 ]; then', "p7", "file-bind-missed", "survivor"),
    ("planted-dir-unchecked", "p7.sh", 'if [ "$d" -eq 1 ] && [ "$f" -eq 1 ]; then',
     'if [ "$f" -eq 1 ]; then', "p7", "dir-bind-missed", "survivor"),
    ("socket-fd-ignored", "p8.sh",
     'if [ "$s" -eq 0 ] && [ "$b" -eq 0 ] && [ "$f" -eq 0 ] && [ "$v" -eq 0 ]',
     'if [ "$s" -eq 0 ] && [ "$b" -eq 0 ] && [ "$v" -eq 0 ]', "p8", "inherited-socket-fd",
     "clean"),
    ("visible-socket-ignored", "p8.sh",
     'if [ "$s" -eq 0 ] && [ "$b" -eq 0 ] && [ "$f" -eq 0 ] && [ "$v" -eq 0 ]',
     'if [ "$s" -eq 0 ] && [ "$b" -eq 0 ] && [ "$f" -eq 0 ]', "p8", "visible-socket-only",
     "clean"),
    ("planted-consistency-unchecked", "p7.sh",
     'if { [ "$d" -eq 1 ] && [ "${e% *}" -lt 1 ]; } ||', "if false &&", "p7",
     "clean-planted-inconsistent", "clean"),
    ("hostnet-signal-unchecked", "p8.sh", 'if [ "$s" -eq 1 ]; then printf', "if true; then printf",
     "p8", "hostnet-socket-fd-only", "hostnet"),
    ("hostnet-any-namespace", "p8.sh", 's=$(rd_bool hostnet shared_net)',
     's=$(rd_uint hostnet shared_ns)', "p8", "hostnet-ipc-only", "hostnet"),
    ("sockbind-signal-unchecked", "p8.sh", 'if [ "$p" -eq 2 ] && [ "$v" -eq 2 ]; then',
     "if true; then", "p8", "sockbind-one-bind", "sockbind"),
    ("visible-planted-aggregate", "p8.sh", 'v=$(rd_uint sockbind visible_planted)',
     'v=$(rd_uint sockbind visible_sockets)', "p8", "sockbind-one-visible-planted", "sockbind"),
    ("isolation-consistency-unchecked", "p8.sh",
     'if [ "$s" -gt 4 ] || [ "$n" -gt "$s" ]', "if false || false", "p8", "clean-net-without-ns",
     "clean"),
    ("sockbind-aggregate-only", "p8.sh", 'p=$(rd_uint sockbind planted_binds)',
     'p=$(rd_uint sockbind socket_binds)', "p8", "sockbind-one-planted", "sockbind"),
    ("namespace-bound-unchecked", "p8.sh", "[ $((s - n)) -gt 3 ]", "[ 0 -gt 3 ]", "p8",
     "sockbind-impossible-ns", "sockbind"),
    ("lazy-zero-marker-accepted", "p3.sh", """printf '%s\\n' "$PROBE_FAIL"; fi ;;""",
     """printf '%s\\n' "$PROBE_NEG"; fi ;;""", "p3", "lazy-marker-zero", "lazy"),
    ("queue-reading-ignored", "p8.sh", 'if [ "$q" -eq 0 ] && [ "$g" -eq 1 ]', 'if [ "$g" -eq 1 ]',
     "p8", "zerobyte-queue-nonzero", "zerobyte"),
]


def arm_verdicts(run: subprocess.CompletedProcess[str], probe: str) -> dict[str, str]:
    """The run printed only ARM lines with known verdicts and one final PROBE
    line, wrote nothing to stderr, and exited 0 exactly when QUALIFIED: a
    crashed or shell-erroring script is not valid output."""
    lines = run.stdout.splitlines()
    assert lines and not run.stderr, (run.returncode, run.stderr)
    assert lines[-1] in (f"PROBE {probe} QUALIFIED", f"PROBE {probe} MISMATCH")
    assert run.returncode == (0 if lines[-1].endswith("QUALIFIED") else 1)
    arms = [line.split() for line in lines[:-1]]
    assert all(len(a) == 3 and a[0] == "ARM" and a[2] in VERDICTS for a in arms)
    verdicts = {a[1]: a[2] for a in arms}
    assert len(verdicts) == len(arms), "an arm reported twice"
    return verdicts


@needs_sh
@pytest.mark.parametrize(("blind", "target", "old", "new", "probe", "case", "changed"),
                         BLIND_TWINS, ids=[f"{t[0]}-{t[4]}" for t in BLIND_TWINS])
def test_blind_twin_is_caught_by_its_fixture(tmp_path: Path, blind: str, target: str, old: str,
                                             new: str, probe: str, case: str,
                                             changed: str) -> None:
    source = (PROBES / target).read_text()
    assert source.count(old) == 1, "the mutation anchor moved; update the blind twin"
    mutated = tmp_path / target
    mutated.write_text(source.replace(old, new))
    script = mutated if target != "lib.sh" else PROBES / f"{probe}.sh"
    lib = mutated if target == "lib.sh" else PROBES / "lib.sh"
    expect = (FIXTURES / probe / f"{case}.expect").read_text()
    real = classify(PROBES / f"{probe}.sh", FIXTURES / probe / f"{case}.readings")
    weakened = classify(script, FIXTURES / probe / f"{case}.readings", lib=lib)
    assert real.stdout == expect
    real_v = arm_verdicts(real, probe)
    weak_v = arm_verdicts(weakened, probe)
    assert weak_v[changed] != real_v[changed], f"blind twin {blind} left arm {changed} unchanged"


@needs_sh
@pytest.mark.parametrize("probe", NAMES)
def test_usage_errors_refuse_with_exit_two(tmp_path: Path, probe: str) -> None:
    unknown = subprocess.run(["sh", str(PROBES / f"{probe}.sh"), "--no-such-flag"],
                             capture_output=True, text=True, check=False, timeout=30)
    assert unknown.returncode == 2 and "REFUSED usage" in unknown.stdout
    absent = classify(PROBES / f"{probe}.sh", tmp_path / "absent.readings")
    assert absent.returncode == 2 and "REFUSED readings-unreadable" in absent.stdout


# ---- Pure lib.sh helpers added for the live-run follow-up (Refs #797) ----
#
# The first live run refused P5 and P6 (Docker's containerd image store
# reports driver "overlayfs", not "overlay2") and left P7 and P8 blind (their
# in-container steps' stderr went to /dev/null). The storage helpers below are
# pure, so their every refusal is a committed case here; each has a blind twin
# that must change its discriminating case.

LIB = PROBES / "lib.sh"
LIB_FIXTURES = FIXTURES / "lib"
HEX = "3f9c" * 16
DROOT = "/var/lib/docker"
SNAP = f"{DROOT}/containerd/daemon/io.containerd.snapshotter.v1.overlayfs/snapshots"

#: mountinfo fixture -> the raw upperdir= overlay_upper must print, or None
#: for a table it must refuse.
MOUNTINFO_CASES = {
    "containerd": f"{SNAP}/57/fs",
    "overlay2": f"{DROOT}/overlay2/{HEX}/diff",
    "overlay2-relative": f"{HEX}/diff",
    "two-root-rows": None,
    "root-not-overlay": None,
    "two-upperdirs": None,
    "malformed-row": None,
    "no-upperdir": None,
    "no-root-row": None,
    "empty": None,
}

#: case -> (kind, docker root, raw upperdir, resolved path or None)
RESOLVE_CASES = {
    "containerd": ("containerd-overlayfs", DROOT, f"{SNAP}/57/fs", f"{SNAP}/57/fs"),
    "overlay2": ("overlay2", DROOT, f"{DROOT}/overlay2/{HEX}/diff",
                 f"{DROOT}/overlay2/{HEX}/diff"),
    "overlay2-relative": ("overlay2", DROOT, f"{HEX}/diff", f"{DROOT}/overlay2/{HEX}/diff"),
    "overlay2-nested-id": ("overlay2", DROOT, f"{DROOT}/overlay2/ab/cd/diff", None),
    "overlay2-other-root": ("overlay2", DROOT, f"/srv/other/overlay2/{HEX}/diff", None),
    "overlay2-workdir": ("overlay2", DROOT, f"{DROOT}/overlay2/{HEX}/work", None),
    "overlay2-relative-root": ("overlay2", "relative/root", f"{HEX}/diff", None),
    "containerd-other-dir": ("containerd-overlayfs", DROOT, f"{DROOT}/other/snapshots/5/fs", None),
    "containerd-dot-dot": ("containerd-overlayfs", DROOT,
                           (f"{DROOT}/containerd/../daemon/io.containerd.snapshotter.v1.overlayfs"
                            "/snapshots/7/fs"), None),
    "containerd-escaped": ("containerd-overlayfs", DROOT,
                           "/var/lib/a\\054b/io.containerd.snapshotter.v1.overlayfs/snapshots/5/fs",
                           None),
    "containerd-relative": ("containerd-overlayfs", DROOT,
                            "io.containerd.snapshotter.v1.overlayfs/snapshots/5/fs", None),
    "containerd-non-numeric": ("containerd-overlayfs", DROOT, f"{SNAP}/x5/fs", None),
    "containerd-trailing-slash": ("containerd-overlayfs", DROOT, f"{SNAP}/57/fs/", None),
    "unknown-kind": ("zfs", DROOT, f"{SNAP}/57/fs", None),
}

#: case -> (docker info driver, DriverStatus "key=value" lines, kind or None)
STORAGE_CASES = {
    "overlay2": ("overlay2", "Backing Filesystem=extfs\nSupports d_type=true", "overlay2"),
    "containerd": ("overlayfs", "driver-type=io.containerd.snapshotter.v1", "containerd-overlayfs"),
    "containerd-other-type": ("overlayfs", "driver-type=io.containerd.snapshotter.v2", None),
    "containerd-no-status": ("overlayfs", "", None),
    "containerd-type-twice": ("overlayfs", ("driver-type=io.containerd.snapshotter.v1\n"
                                            "driver-type=io.containerd.snapshotter.v1"), None),
    "other-driver": ("devicemapper", "driver-type=io.containerd.snapshotter.v1", None),
}

#: A stderr body longer than the 2 KiB bound, carrying an escape sequence, a
#: high byte, a carriage return and text that would read as a verdict line.
DIAG_BODY = (b"\x1b[31mARM clean CONFIRMED_NEGATIVE\rPROBE p7 QUALIFIED\n"
             b"ARM clean CONFIRMED_NEGATIVE\nPROBE p7 QUALIFIED\n\xff"
             + b"find: '/root': Permission denied\n" * 150)
DIAG_BOUND = 2048


def lib_call(lib: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["sh", "-c", '. "$1"; shift; "$@"', "sh", str(lib), *args],
                          capture_output=True, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                          check=False, timeout=30)


def helper_result(lib: Path, kind: str, case: str) -> str | None:
    """The helper's single output line, or None when it refused. A refusal
    must print nothing; any stderr is invalid output for a pure helper."""
    if kind == "mountinfo":
        run = lib_call(lib, "overlay_upper", str(LIB_FIXTURES / f"mountinfo-{case}.txt"))
    elif kind == "resolve":
        run = lib_call(lib, "upper_resolve", *RESOLVE_CASES[case][:3])
    elif kind == "storage":
        run = lib_call(lib, "storage_kind_from", *STORAGE_CASES[case][:2])
    else:
        raise AssertionError(kind)
    assert not run.stderr, run.stderr
    if run.returncode != 0:
        assert run.stdout == b""
        return None
    lines = run.stdout.decode().splitlines()
    assert len(lines) == 1, lines
    return lines[0]


def expected(kind: str, case: str) -> str | None:
    if kind == "mountinfo":
        return MOUNTINFO_CASES[case]
    if kind == "resolve":
        return RESOLVE_CASES[case][3]
    return STORAGE_CASES[case][2]


HELPER_CASES = ([("mountinfo", c) for c in MOUNTINFO_CASES]
                + [("resolve", c) for c in RESOLVE_CASES]
                + [("storage", c) for c in STORAGE_CASES])


def test_every_mountinfo_fixture_has_a_case() -> None:
    files = {p.name for p in LIB_FIXTURES.iterdir()}
    assert files == {f"mountinfo-{c}.txt" for c in MOUNTINFO_CASES}


@needs_sh
@pytest.mark.parametrize(("kind", "case"), HELPER_CASES,
                         ids=[f"{k}-{c}" for k, c in HELPER_CASES])
def test_storage_helper_case(kind: str, case: str) -> None:
    assert helper_result(LIB, kind, case) == expected(kind, case)


#: (blind copy name, exact lib.sh text, weakened text, helper kind, case)
LIB_TWINS = [
    ("last-root-row-taken", 'if (bad || rows < 1 || n != 1 || fs != "overlay") exit 1',
     'if (bad || rows < 1 || n < 1 || fs != "overlay") exit 1', "mountinfo", "two-root-rows"),
    ("root-fstype-unchecked", 'if (bad || rows < 1 || n != 1 || fs != "overlay") exit 1',
     "if (bad || rows < 1 || n != 1) exit 1", "mountinfo", "root-not-overlay"),
    ("malformed-rows-ignored", 'if (bad || rows < 1 || n != 1 || fs != "overlay") exit 1',
     'if (rows < 1 || n != 1 || fs != "overlay") exit 1', "mountinfo", "malformed-row"),
    ("upperdir-count-unchecked", 'if (u != 1 || v == "") exit 1', 'if (u < 1 || v == "") exit 1',
     "mountinfo", "two-upperdirs"),
    ("overlay2-id-unchecked", "case $_id in '' | *[!0-9a-f]*) return 1 ;; esac", ":", "resolve",
     "overlay2-nested-id"),
    ("snapshot-dir-unchecked",
     ("case ${_base%/*} in /?*/io.containerd.snapshotter.v1.overlayfs/snapshots) ;; "
      "*) return 1 ;; esac"), ":", "resolve", "containerd-other-dir"),
    ("dot-components-accepted", "case /$_x/ in */./* | */../*) return 1 ;; esac", ":", "resolve",
     "containerd-dot-dot"),
    ("escaped-path-accepted", "case $_x in '' | *//* | *[!A-Za-z0-9/._-]*) return 1 ;; esac",
     "case $_x in '' | *//*) return 1 ;; esac", "resolve", "containerd-escaped"),
    ("driver-type-trusted", '[ "$_t" = io.containerd.snapshotter.v1 ] || return 1', ":",
     "storage", "containerd-other-type"),
    ("driver-type-count-unchecked", "END { if (n != 1) exit 1; print v }", "END { print v }",
     "storage", "containerd-type-twice"),
]


@needs_sh
@pytest.mark.parametrize(("blind", "old", "new", "kind", "case"), LIB_TWINS,
                         ids=[t[0] for t in LIB_TWINS])
def test_storage_helper_blind_twin_is_caught(tmp_path: Path, blind: str, old: str, new: str,
                                             kind: str, case: str) -> None:
    source = LIB.read_text()
    assert source.count(old) == 1, "the mutation anchor moved; update the blind twin"
    mutated = tmp_path / "lib.sh"
    mutated.write_text(source.replace(old, new))
    assert helper_result(LIB, kind, case) == expected(kind, case)
    assert helper_result(mutated, kind, case) != expected(kind, case), blind


def diag_output(lib: Path, tmp_path: Path) -> bytes:
    err = tmp_path / "step.err"
    err.write_bytes(DIAG_BODY)
    run = lib_call(lib, "step_diag", "clean", "scan", "3", str(err))
    assert run.returncode == 0 and not run.stderr, run.stderr
    return run.stdout


def expected_diag() -> bytes:
    """Exactly what step_diag must print for DIAG_BODY: the status line, the
    first 2048 bytes with every byte outside printable ASCII made '?', one
    prefixed line each (the unterminated last line too), then the truncation."""
    kept = bytes(b if 32 <= b < 127 or b == 10 else 63 for b in DIAG_BODY[:DIAG_BOUND])
    lines = kept.split(b"\n")
    if kept.endswith(b"\n"):
        lines.pop()
    return (b"INFO diag clean scan exit 3\n"
            + b"".join(b"INFO diag clean scan stderr: " + line + b"\n" for line in lines)
            + f"INFO diag clean scan stderr-truncated {len(DIAG_BODY)}\n".encode())


@needs_sh
def test_step_diag_prints_exactly_the_bounded_scrubbed_prefix(tmp_path: Path) -> None:
    assert not DIAG_BODY[:DIAG_BOUND].endswith(b"\n"), "the case needs an unterminated last line"
    out = diag_output(LIB, tmp_path)
    assert out == expected_diag()
    # stderr carried complete verdict-shaped lines; none prints as one.
    assert not any(line.startswith((b"ARM ", b"PROBE ")) for line in out.splitlines())


@needs_sh
def test_step_diag_reports_the_status_alone_for_empty_stderr(tmp_path: Path) -> None:
    err = tmp_path / "empty.err"
    err.write_bytes(b"")
    run = lib_call(LIB, "step_diag", "fault", "inventory", "4", str(err))
    assert run.returncode == 0 and run.stderr == b""
    assert run.stdout == b"INFO diag fault inventory exit 4\n"


#: A step that prints to stdout, floods stderr far past the bound, and exits 3.
#: Under `set -e`, a stderr writer killed by a closed pipe exits 141 instead,
#: so the returned status shows whether the collector kept draining.
FLOOD = "set -e; printf out; head -c 100000 /dev/zero >&2; exit 3"


#: The shells the capture is qualified under. dash (the runner VM's and CI's
#: /bin/sh) applies `set -e` inside a pipeline subshell where bash does not;
#: running both means a bash-only pass cannot hide that difference.
SHELLS = ["sh"] + (["dash"] if shutil.which("dash") else []) + (
    ["bash"] if shutil.which("bash") else [])
CAPTURE_SCRIPT = ('. "$1"; rc=0; step_capture "$2" sh -c "$3" || rc=$?;'
                  ' printf "\\nrc=%s\\n" "$rc"')


def capture_run(lib: Path, tmp_path: Path, err: Path | None = None,
                shell: str = "sh") -> tuple[bytes, Path]:
    err = err or tmp_path / "flood.err"
    run = subprocess.run([shell, "-eu", "-c", CAPTURE_SCRIPT, shell, str(lib), str(err), FLOOD],
                         capture_output=True, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                         check=False, timeout=60)
    assert run.returncode == 0 and run.stderr == b"", run.stderr
    return run.stdout, err


def capture_is_bounded(stdout: bytes, err: Path) -> bool:
    """stdout passed through, the step's own status returned, at most the
    bound kept on disk, and the rest counted exactly rather than stored."""
    return (stdout == b"out\nrc=3\n" and err.read_bytes() == b"\0" * DIAG_BOUND
            and (err.parent / f"{err.name}.rest").read_text() == f"{100000 - DIAG_BOUND}\n")


@needs_sh
@pytest.mark.parametrize("shell", SHELLS)
def test_step_capture_bounds_stderr_while_the_step_runs(tmp_path: Path, shell: str) -> None:
    assert capture_is_bounded(*capture_run(LIB, tmp_path, shell=shell))


@needs_sh
@pytest.mark.parametrize("shell", SHELLS)
def test_step_capture_returns_a_failing_step_status_under_errexit(tmp_path: Path,
                                                                  shell: str) -> None:
    """The regression case from stage 1: under `sh -e` (dash), a step that
    fails must return its own status, not 125."""
    script = '. "$1"; rc=0; step_capture "$2" sh -c "exit 7" || rc=$?; echo "rc=$rc"'
    run = subprocess.run([shell, "-eu", "-c", script, shell, str(LIB), str(tmp_path / "e.err")],
                         capture_output=True, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                         check=False, timeout=30)
    assert (run.returncode, run.stdout, run.stderr) == (0, b"rc=7\n", b"")


def unwritable_capture(lib: Path, tmp_path: Path, shell: str = "sh") -> bytes:
    """The diagnostic file cannot be created (its directory does not exist):
    the collector must still drain, and the step's own status must return."""
    stdout, _ = capture_run(lib, tmp_path, tmp_path / "missing-dir" / "flood.err", shell=shell)
    return stdout


@needs_sh
@pytest.mark.parametrize("shell", SHELLS)
def test_step_capture_keeps_the_status_when_diagnostics_cannot_be_stored(tmp_path: Path,
                                                                         shell: str) -> None:
    assert unwritable_capture(LIB, tmp_path, shell) == b"out\nrc=3\n"


#: (blind copy name, exact lib.sh text, weakened text)
DIAG_TWINS = [
    ("stderr-unbounded", 'head -c 2048 -- "$4"', 'cat -- "$4"'),
    ("stderr-unscrubbed", "LC_ALL=C tr -c '\\n[:print:]' '?'", "cat"),
    ("stderr-prefix-removed", 'print "INFO diag " a " " s " stderr: " $0', "print $0"),
    ("stderr-lines-after-first-dropped",
     '{ print "INFO diag " a " " s " stderr: " $0 }',
     'NR == 1 { print "INFO diag " a " " s " stderr: " $0 }'),
]


@needs_sh
@pytest.mark.parametrize(("blind", "old", "new"), DIAG_TWINS, ids=[t[0] for t in DIAG_TWINS])
def test_step_diag_blind_twin_is_caught(tmp_path: Path, blind: str, old: str, new: str) -> None:
    source = LIB.read_text()
    assert source.count(old) == 1, "the mutation anchor moved; update the blind twin"
    mutated = tmp_path / "lib.sh"
    mutated.write_text(source.replace(old, new))
    assert diag_output(LIB, tmp_path) == expected_diag()
    assert diag_output(mutated, tmp_path) != expected_diag(), blind


CAPTURE_TWINS = [
    ("drain-unbounded", 'if ! dd bs=1 count=2048 of="$1" 2>/dev/null; then',
     'if ! cat >"$1"; then'),
    ("step-status-lost", 'return "$_st"\n}', "return 0\n}"),
]


@needs_sh
@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize(("blind", "old", "new"), CAPTURE_TWINS, ids=[t[0] for t in CAPTURE_TWINS])
def test_step_capture_blind_twin_is_caught(tmp_path: Path, blind: str, old: str, new: str,
                                           shell: str) -> None:
    source = LIB.read_text()
    assert source.count(old) == 1, "the mutation anchor moved; update the blind twin"
    mutated = tmp_path / "twin" / "lib.sh"
    mutated.parent.mkdir()
    mutated.write_text(source.replace(old, new))
    real = tmp_path / "real"
    real.mkdir()
    assert capture_is_bounded(*capture_run(LIB, real, shell=shell))
    weak = tmp_path / "weak"
    weak.mkdir()
    assert not capture_is_bounded(*capture_run(mutated, weak, shell=shell)), blind


@needs_sh
@pytest.mark.parametrize("shell", SHELLS)
def test_step_capture_drain_fallback_twin_is_caught(tmp_path: Path, shell: str) -> None:
    old = "then cat >/dev/null; return 0; fi"
    source = LIB.read_text()
    assert source.count(old) == 1, "the mutation anchor moved; update the blind twin"
    mutated = tmp_path / "twin" / "lib.sh"
    mutated.parent.mkdir()
    mutated.write_text(source.replace(old, "then return 0; fi"))
    real = tmp_path / "real"
    real.mkdir()
    weak = tmp_path / "weak"
    weak.mkdir()
    assert unwritable_capture(LIB, real, shell) == b"out\nrc=3\n"
    assert unwritable_capture(mutated, weak, shell) != b"out\nrc=3\n"


#: The call sites that must route each in-container step through step_capture
#: and keep container stdout out of verdict output. A static check: the live
#: callers need root and Docker, so CI pins their exact wiring text instead.
WIRING = {
    "p5.sh": ['step_capture "$PROBE_SCRATCH/writes.err" docker exec "$cid" sh -c',
              '        sh "$disk" >/dev/null || _rc=$?',
              'upper_dir_of "$cid" 9'],
    "p6.sh": ['upper_dir_of "$c1" 9', 'upper_dir_of "$c2" 8'],
    "p7.sh": ['out=$(step_capture "$PROBE_SCRATCH/$_arm.err" docker start -a "$cid") || _rc=$?',
              '-- "$PROBE_IMAGE_ID" sh -c "$SCAN_LIB$INVENTORY"',
              'scan "$dirs/pruned" "$mp" xdev "" -type d -writable >>"$dirs/dirs"',
              'scan "$dirs/pruned" "$mp" xdev "" -type d "$@" >>"$dirs/dirs"',
              'elif [ "$_rc" -eq 0 ] && scan_report "$_arm" "$out"; then',
              'step_diag "$_arm" inventory "$_rc" "$PROBE_SCRATCH/$_arm.err"'],
    "p8.sh": ['b=$(step_capture "$PROBE_SCRATCH/$1.binds.err" socket_binds "$2") || _rc=$?',
              'v=$(step_capture "$PROBE_SCRATCH/$1.scan.err" docker exec "$2" sh -c "$SCAN_LIB"',
              'o=$(scan "$t/pruned" / all "/proc /sys" -type s)',
              'if [ "$_rc" -eq 0 ] && scan_report "$1" "$v" && is_uint "${SCAN_HEAD% *}"',
              'step_diag "$1" binds "$_rc" "$PROBE_SCRATCH/$1.binds.err"',
              'step_diag "$1" scan "$_rc" "$PROBE_SCRATCH/$1.scan.err"'],
}


@pytest.mark.parametrize("script", sorted(WIRING))
def test_live_steps_are_wired_through_the_bounded_capture(script: str) -> None:
    text = (PROBES / script).read_text()
    for line in WIRING[script]:
        assert text.count(line) == 1, line
    assert "2>/dev/null) && is_uint" not in text, "an in-container step is blind again"
    assert "find / " not in text and 'find "$mp" -xdev' not in text, "a scan bypasses SCAN_LIB"


# ---- upper_dir_of against a stubbed docker and procfs ----
#
# The live guards (pid revalidation before and after the proof, the graph
# driver cross-check, the marker read back through the held handle) run here
# against a stub `docker` on PATH and a stub procfs (PROBE_PROC), so removing
# any of them turns a case. No Docker, root or VM is used.

FAKE_DOCKER = r"""#!/bin/sh
s=$FAKE_STATE
case $1 in
inspect)
    case $3 in
    *State.Pid*)
        n=$(cat "$s/pid-calls" 2>/dev/null || echo 0)
        n=$((n + 1))
        echo "$n" >"$s/pid-calls"
        if [ "$n" -ge "${FAKE_STAT_CHANGES_AT:-99}" ]; then
            sed 's/ 19 / 1919 /' "$PROBE_PROC/4242/stat" >"$s/stat"
            cat "$s/stat" >"$PROBE_PROC/4242/stat"
        fi
        if [ "$n" -ge "${FAKE_PID_CHANGES_AT:-99}" ]; then echo 4343; else echo 4242; fi ;;
    *UpperDir*) cat "$s/graph-upper" ;;
    *) exit 1 ;;
    esac ;;
exec)
    [ -n "${FAKE_MARK_DIR:-}" ] || exit 0
    printf '%s%s' "${FAKE_MARK_CONTENT:-$7}" "${FAKE_MARK_SUFFIX:-}" >"$FAKE_MARK_DIR/tmp/$7" ;;
*) exit 1 ;;
esac
"""

#: case -> (storage kind, options). Options: pid_changes_at (the inspect call
#: that first reports another pid), stat_changes_at (the inspect call at which
#: pid 4242 becomes a different process: same pid, new start time), mark
#: ("upper", "other" or "none"), content (a wrong marker body), suffix (bytes
#: after the token), tmp_link (upper's tmp is a symlink to other's), graph
#: ("same" or "other"), layout ("snapshot" or "elsewhere"), fd ("8" or "9").
UPPER_CASES: dict[str, tuple[str, dict[str, str]]] = {
    "verified": ("containerd-overlayfs", {}),
    "verified-fd8": ("containerd-overlayfs", {"fd": "8"}),
    "start-time-changes": ("containerd-overlayfs", {"stat_changes_at": "2"}),
    "marker-trailing-newline": ("containerd-overlayfs", {"suffix": "\n"}),
    "marker-tmp-symlink": ("containerd-overlayfs", {"mark": "other", "tmp_link": "1"}),
    "overlay2-agrees": ("overlay2", {"graph": "same"}),
    "overlay2-disagrees": ("overlay2", {"graph": "other"}),
    "pid-changes-before-proof": ("containerd-overlayfs", {"pid_changes_at": "2"}),
    "pid-changes-after-proof": ("containerd-overlayfs", {"pid_changes_at": "3"}),
    "marker-elsewhere": ("containerd-overlayfs", {"mark": "other"}),
    "marker-absent": ("containerd-overlayfs", {"mark": "none"}),
    "marker-wrong-content": ("containerd-overlayfs", {"content": "stale"}),
    "shape-refused": ("containerd-overlayfs", {"layout": "elsewhere"}),
}

UPPER_EXPECT = {
    "verified": "UPPER-HELD",
    "verified-fd8": "UPPER-HELD",
    "start-time-changes": "PROBE t REFUSED container-pid-changed",
    "marker-trailing-newline": "PROBE t REFUSED upperdir-unverified",
    "marker-tmp-symlink": "PROBE t REFUSED upperdir-unverified",
    "overlay2-agrees": "UPPER-HELD",
    "overlay2-disagrees": "PROBE t REFUSED upperdir-disagrees",
    "pid-changes-before-proof": "PROBE t REFUSED container-pid-changed",
    "pid-changes-after-proof": "PROBE t REFUSED container-pid-changed",
    "marker-elsewhere": "PROBE t REFUSED upperdir-unverified",
    "marker-absent": "PROBE t REFUSED upperdir-unverified",
    "marker-wrong-content": "PROBE t REFUSED upperdir-unverified",
    "shape-refused": "PROBE t REFUSED upperdir-shape",
}


def upper_call(lib: Path, tmp_path: Path, case: str) -> str:
    kind, opt = UPPER_CASES[case]
    base = tmp_path / "host"
    root = base / "docker"
    if kind == "overlay2":
        upper = root / "overlay2" / HEX / "diff"
    elif opt.get("layout") == "elsewhere":
        upper = base / "elsewhere" / "57" / "fs"
    else:
        upper = base / "cd" / "io.containerd.snapshotter.v1.overlayfs" / "snapshots" / "57" / "fs"
    other = base / "other"
    for d in (upper, other / "tmp", root):
        d.mkdir(parents=True, exist_ok=True)
    if opt.get("tmp_link"):
        (upper / "tmp").symlink_to(other / "tmp")
    else:
        (upper / "tmp").mkdir()
    proc = base / "proc" / "4242"
    proc.mkdir(parents=True)
    (proc / "stat").write_text("4242 (sleep) S " + " ".join(str(n) for n in range(1, 50)) + "\n")
    (proc / "mountinfo").write_text(
        f"1012 900 0:142 / / rw,relatime - overlay overlay rw,lowerdir=/l,upperdir={upper},"
        f"workdir=/w\n1013 1012 0:145 / /proc rw,nosuid - proc proc rw\n")
    state = base / "state"
    state.mkdir()
    (state / "graph-upper").write_text(f"{upper if opt.get('graph') != 'other' else other}\n")
    bindir = base / "bin"
    bindir.mkdir()
    (bindir / "docker").write_text(FAKE_DOCKER)
    (bindir / "docker").chmod(0o755)
    # marker_matches runs python3 -I; the interpreter running this test is one.
    pydir = base / "py"
    pydir.mkdir()
    (pydir / "python3").symlink_to(sys.executable)
    env = {"PATH": f"{bindir}:{pydir}:/usr/bin:/bin", "LC_ALL": "C", "FAKE_STATE": str(state),
           "PROBE_PROC": str(base / "proc")}
    mark = opt.get("mark", "upper")
    if mark != "none":
        env["FAKE_MARK_DIR"] = str(upper if mark == "upper" else other)
    if "content" in opt:
        env["FAKE_MARK_CONTENT"] = opt["content"]
    if "pid_changes_at" in opt:
        env["FAKE_PID_CHANGES_AT"] = opt["pid_changes_at"]
    if "stat_changes_at" in opt:
        env["FAKE_STAT_CHANGES_AT"] = opt["stat_changes_at"]
    if "suffix" in opt:
        env["FAKE_MARK_SUFFIX"] = opt["suffix"]
    fd = opt.get("fd", "9")
    script = ('. "$1"; PROBE_NAME=t; PROBE_STORAGE=$2; PROBE_DOCKER_ROOT=$3;'
              ' upper_dir_of cid "$5";'
              ' if [ "$PROBE_UPPER" = "/proc/$$/fd/$5" ] && [ "$PROBE_UPPER" -ef "$4" ];'
              ' then echo UPPER-HELD; else echo UPPER-OTHER; fi')
    run = subprocess.run(["sh", "-eu", "-c", script, "sh", str(lib), kind, str(root), str(upper),
                          fd],
                         capture_output=True, text=True, env=env, check=False, timeout=30)
    lines = run.stdout.splitlines()
    assert lines and not run.stderr, (run.returncode, run.stdout, run.stderr)
    assert run.returncode == (0 if lines[-1].startswith("UPPER") else 2)
    return lines[-1]


def test_upper_cases_have_expectations() -> None:
    assert set(UPPER_CASES) == set(UPPER_EXPECT)


@needs_sh
@pytest.mark.parametrize("case", sorted(UPPER_CASES))
def test_upper_dir_of_case(tmp_path: Path, case: str) -> None:
    assert upper_call(LIB, tmp_path, case) == UPPER_EXPECT[case]


#: (blind copy name, exact lib.sh text, weakened text, case)
UPPER_TWINS = [
    ("pid-revalidation-blind", '[ "$_n" = "$3" ] && [ "$_p" = "$2" ]', ":",
     "pid-changes-before-proof"),
    ("final-pid-recheck-removed",
     ("    _upper_pid_same \"$1\" \"$_pid\" \"$_ident\" || probe_die 'container-pid-changed'\n"
      "    PROBE_UPPER=$_held"), "    PROBE_UPPER=$_held", "pid-changes-after-proof"),
    ("graph-driver-unchecked", "[ \"$_gd\" = \"$_up\" ] || probe_die 'upperdir-disagrees'", ":",
     "overlay2-disagrees"),
    ("start-time-unchecked", '[ "$_n" = "$3" ] && [ "$_p" = "$2" ]', '[ "$_p" = "$2" ]',
     "start-time-changes"),
    ("marker-content-unchecked", "*) probe_die 'upperdir-unverified' ;;", "*) ;;",
     "marker-wrong-content"),
    ("marker-resolve-unrestricted",
     ("how = OpenHow(os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK, 0,\n"
      "              RESOLVE_NO_XDEV | RESOLVE_NO_SYMLINKS | RESOLVE_BENEATH)"),
     "how = OpenHow(os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK, 0, 0)", "marker-tmp-symlink"),
]


@needs_sh
@pytest.mark.parametrize(("blind", "old", "new", "case"), UPPER_TWINS,
                         ids=[t[0] for t in UPPER_TWINS])
def test_upper_dir_of_blind_twin_is_caught(tmp_path: Path, blind: str, old: str, new: str,
                                           case: str) -> None:
    source = LIB.read_text()
    assert source.count(old) == 1, "the mutation anchor moved; update the blind twin"
    mutated = tmp_path / "twin-lib.sh"
    mutated.write_text(source.replace(old, new))
    real = tmp_path / "real"
    real.mkdir()
    weak = tmp_path / "weak"
    weak.mkdir()
    assert upper_call(LIB, real, case) == UPPER_EXPECT[case]
    assert upper_call(mutated, weak, case) != UPPER_EXPECT[case], blind


#: The mount-crossing twin: the same lookup with RESOLVE_NO_XDEV dropped.
XDEV_TWIN = ("RESOLVE_NO_XDEV | RESOLVE_NO_SYMLINKS | RESOLVE_BENEATH)",
             "RESOLVE_NO_SYMLINKS | RESOLVE_BENEATH)")


@needs_sh
def test_marker_proof_refuses_a_bind_mounted_tmp(tmp_path: Path) -> None:
    """Another tree's tmp, bind-mounted over the held upper's tmp, must not
    authenticate it. Needs a mount, so it runs only where one can be made
    (root with CAP_SYS_ADMIN: the runner VM's stage-1 root run)."""
    held = tmp_path / "held"
    (held / "tmp").mkdir(parents=True)
    real = tmp_path / "real-tmp"
    real.mkdir()
    tok = "skillc-dev-probe-id-" + "ab" * 16
    (real / tok).write_text(tok)
    mounted = subprocess.run(["mount", "--bind", str(real), str(held / "tmp")],
                             capture_output=True, check=False, timeout=30)
    if mounted.returncode != 0:
        pytest.skip("cannot bind-mount here (needs root with CAP_SYS_ADMIN)")
    try:
        source = LIB.read_text()
        assert source.count(XDEV_TWIN[0]) == 1, "the mutation anchor moved; update the twin"
        twin = tmp_path / "twin-lib.sh"
        twin.write_text(source.replace(*XDEV_TWIN))
        script = '. "$1"; exec 9<"$2"; if marker_matches 9 "$3"; then echo MATCH; else echo NO; fi'
        env = {"PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin", "LC_ALL": "C"}
        results = [subprocess.run(["sh", "-eu", "-c", script, "sh", str(lib), str(held), tok],
                                  capture_output=True, text=True, env=env, check=False,
                                  timeout=30).stdout.strip() for lib in (LIB, twin)]
    finally:
        subprocess.run(["umount", str(held / "tmp")], check=False, timeout=30)
    assert results == ["NO", "MATCH"]



# ---- The in-container prune rule (lib.sh SCAN_LIB), on crafted trees ----
#
# The first live P7/P8 run read OBSERVATION_FAILED on every live arm: the
# image has four root-only directories the probe uid cannot search, and the
# whole-filesystem find exited nonzero on them. The rule: a directory the uid
# cannot SEARCH, by access(2) AND by the mode bits of its class, and that it
# does not own, is unreachable by a fresh path lookup, so it is pruned and
# reported. Any other denial (an ACL, a probe-owned directory, a newline
# name), or a directory it can search but not read, FAILS the scan. Each case
# runs the real SCAN_LIB as nobody (dropped from root) over a root-owned tree
# under a short, traversable /tmp parent, so the tree's permission bits apply.

ROOT_RUN = os.geteuid() == 0
NOBODY = 65534
needs_root_drop = pytest.mark.skipif(not ROOT_RUN or shutil.which("find") is None,
                                     reason="needs root (to build root-owned trees and "
                                            "drop to nobody) and find")

#: Permission classes for nobody, which is "other" on these root-owned trees.
MODES = {
    "open": 0o755,      # search + read, no write
    "open-w": 0o757,    # search + read + write
    "noexec": 0o750,    # no search
    "wnx": 0o752,       # write, no search
    "xnr": 0o751,       # search, no read
    "owner-noexec": 0o600,  # for a nobody-owned directory: no search by any class
}

#: The image's four root-only directories from the live run.
IMAGE_PRUNED = ["root", "etc/ssl/private", "var/cache/ldconfig", "var/cache/apt/archives/partial"]
NL_DIR = "odd\nname"


def _image_tree() -> list[tuple[str, str, str]]:
    """Every pruned directory hides a writable directory and a socket, so a
    prune that descended, or one that failed to prune, would find them."""
    tree = [(d, "dir", "open") for d in ("etc", "etc/ssl", "var", "var/cache", "var/cache/apt",
                                         "var/cache/apt/archives")]
    for d in IMAGE_PRUNED:
        tree += [(d, "dir", "noexec"), (f"{d}/inner", "dir", "open-w"), (f"{d}/s.sock", "sock", "")]
    return tree


#: case -> entries (relative path, "dir"/"sock"/"nobody-dir", final class),
#: parents first. "nobody-dir" is a directory owned by the scanning uid.
SCAN_TREES: dict[str, list[tuple[str, str, str]]] = {
    "image-shape": _image_tree(),
    "searchable-not-readable": [("opt", "dir", "open"), ("opt/locked", "dir", "xnr"),
                                ("opt/locked/inner", "dir", "open-w")],
    "survivor-beside-pruned": _image_tree() + [("srv", "dir", "open"),
                                               ("srv/drop", "dir", "open-w"),
                                               ("srv/s.sock", "sock", "")],
    "write-without-search": [("spool", "dir", "wnx"), ("spool/inner", "dir", "open-w")],
    "probe-owned-unsearchable": [("home", "dir", "open"),
                                 ("home/mine", "nobody-dir", "owner-noexec")],
    "newline-name": [(NL_DIR, "dir", "noexec")],
}

#: (writable-scan ok, socket-scan ok, writable dirs, sockets, pruned lines)
ScanResult = tuple[bool, bool, list[str], list[str], list[str]]

#: case -> its ScanResult. A failed scan's partial output is never evidence,
#: so it is not compared.
SCAN_EXPECT: dict[str, ScanResult] = {
    "image-shape": (True, True, [], [], [f"PRUNED {d}" for d in IMAGE_PRUNED]),
    "searchable-not-readable": (False, False, [], [], []),
    "survivor-beside-pruned": (True, True, ["srv/drop"], ["srv/s.sock"],
                               [f"PRUNED {d}" for d in IMAGE_PRUNED]),
    "write-without-search": (True, True, [], [], ["PRUNED-W spool"]),
    "probe-owned-unsearchable": (False, False, [], [], []),
    "newline-name": (False, False, [], [], []),
}

SCAN_SCRIPT = """
set -euf
w=0
scan "$1/w.pruned" "$2" all "" -type d -writable >"$1/w.match" || w=$?
s=0
scan "$1/s.pruned" "$2" all "" -type s >"$1/s.match" || s=$?
echo "rc=$w $s"
sed "s|^$2/||" "$1/w.match" | sed "s/^/W /"
sed "s|^$2/||" "$1/s.match" | sed "s/^/S /"
if [ "$w" = 0 ]; then pruned_lines "$1/w.pruned" | sed "s|$2/||"; fi
"""


def scan_lib_text(lib: Path) -> str:
    run = subprocess.run(["sh", "-c", '. "$1"; printf "%s" "$SCAN_LIB"', "sh", str(lib)],
                         capture_output=True, text=True, check=True, timeout=30)
    return run.stdout


def short_dir(prefix: str) -> Path:
    """A fresh directory directly under /tmp (short, so socket paths fit;
    /tmp is world-searchable, so nobody can reach it)."""
    path = Path(tempfile.mkdtemp(prefix=prefix, dir="/tmp"))
    path.chmod(0o755)
    return path


def build_tree(base: Path, case: str, made: list[Path]) -> None:
    """Create the case's tree, registering each directory in `made` as it is
    created, then apply the final modes children first."""
    final: dict[Path, str] = {base: "open"}
    for rel, kind, cls in SCAN_TREES[case]:
        path = base / rel
        if kind == "sock":
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.bind(str(path))
            continue
        path.mkdir()
        made.append(path)
        if kind == "nobody-dir":
            os.chown(path, NOBODY, NOBODY)
        final[path] = cls
    for path in sorted(final, key=lambda p: len(p.parts), reverse=True):
        path.chmod(MODES[final[path]])


def run_scan_script(lib: Path, shell: str, script: str,
                    *args: str) -> subprocess.CompletedProcess[str]:
    """Run SCAN_LIB plus a script as nobody, with the given arguments."""
    return subprocess.run([shell, "-c", scan_lib_text(lib) + script, shell, *args],
                          capture_output=True, text=True, cwd="/",
                          env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"}, check=False, timeout=60,
                          user=NOBODY, group=NOBODY, extra_groups=[])


def run_scan(lib: Path, case: str, shell: str) -> ScanResult:
    tree = short_dir("ss-")
    work = short_dir("so-")
    made: list[Path] = []
    try:
        os.chown(work, NOBODY, NOBODY)
        build_tree(tree, case, made)
        run = run_scan_script(lib, shell, SCAN_SCRIPT, str(work), str(tree))
    finally:
        for path in [tree, *made]:
            path.chmod(0o755)
        shutil.rmtree(tree, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)
    assert run.returncode == 0, (run.returncode, run.stdout, run.stderr)
    lines = run.stdout.splitlines()
    assert lines and lines[0].startswith("rc="), (run.stdout, run.stderr)
    w_rc, s_rc = lines[0][3:].split()
    w_ok, s_ok = w_rc == "0", s_rc == "0"
    found_w = sorted(line[2:] for line in lines[1:] if line.startswith("W ")) if w_ok else []
    found_s = sorted(line[2:] for line in lines[1:] if line.startswith("S ")) if s_ok else []
    pruned = sorted(line for line in lines[1:] if line.startswith("PRUNED")) if w_ok else []
    return (w_ok, s_ok, found_w, found_s, pruned)


def scan_expected(case: str) -> ScanResult:
    w_ok, s_ok, w, so, pr = SCAN_EXPECT[case]
    return (w_ok, s_ok, sorted(w), sorted(so), sorted(pr))


def test_scan_cases_have_expectations() -> None:
    assert set(SCAN_TREES) == set(SCAN_EXPECT)


@needs_root_drop
@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("case", sorted(SCAN_TREES))
def test_scan_prune_rule_case(case: str, shell: str) -> None:
    assert run_scan(LIB, case, shell) == scan_expected(case)


@needs_root_drop
@pytest.mark.skipif(shutil.which("setfacl") is None, reason="setfacl is required")
def test_scan_fails_on_a_denial_the_mode_bits_do_not_explain() -> None:
    """The mode bits grant nobody search, but a named-user ACL entry denies
    it: access(2) and the mode disagree, so the scan must fail, not prune."""
    tree = short_dir("sa-")
    work = short_dir("so-")
    try:
        os.chown(work, NOBODY, NOBODY)
        (tree / "acl").mkdir()
        (tree / "acl").chmod(0o755)
        acl = subprocess.run(["setfacl", "-m", f"u:{NOBODY}:---", str(tree / "acl")],
                             capture_output=True, check=False, timeout=30)
        if acl.returncode != 0:
            pytest.skip("this filesystem refuses POSIX ACLs")
        script = 'scan "$1/p" "$2" all "" -type d -writable >/dev/null && echo OK || echo FAILED'
        run = run_scan_script(LIB, "sh", script, str(work), str(tree))
    finally:
        shutil.rmtree(tree, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)
    assert run.stdout.strip() == "FAILED", (run.stdout, run.stderr)


#: Two -xdev calls sharing one report, and an exclusion that hides a
#: directory which would fail the scan if it were examined.
APPEND_SCRIPT = """
set -euf
scan "$1/p" "$2/a" xdev "" -type d -writable >/dev/null
scan "$1/p" "$2/b" xdev "$2/b/skip" -type d -writable >/dev/null
pruned_lines "$1/p" | sed "s|$2/||"
"""


def run_append(lib: Path) -> list[str]:
    tree = short_dir("sx-")
    work = short_dir("so-")
    made: list[Path] = []
    try:
        os.chown(work, NOBODY, NOBODY)
        for rel in ("a", "a/n", "b", "b/n", "b/skip", "b/skip/locked"):
            (tree / rel).mkdir()
            made.append(tree / rel)
        for rel, cls in (("a/n", "noexec"), ("b/n", "noexec"), ("b/skip/locked", "xnr"),
                         ("b/skip", "open"), ("a", "open"), ("b", "open")):
            (tree / rel).chmod(MODES[cls])
        run = run_scan_script(lib, "sh", APPEND_SCRIPT, str(work), str(tree))
    finally:
        for path in [tree, *made]:
            path.chmod(0o755)
        shutil.rmtree(tree, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)
    return [f"rc={run.returncode}", *sorted(run.stdout.splitlines())]


@needs_root_drop
def test_scan_appends_across_calls_and_honours_exclusions() -> None:
    assert run_append(LIB) == ["rc=0", "PRUNED a/n", "PRUNED b/n"]


@needs_root_drop
def test_scan_fails_on_a_missing_root() -> None:
    work = short_dir("so-")
    try:
        os.chown(work, NOBODY, NOBODY)
        script = 'scan "$1/p" "$1/absent" all "" -type d && echo OK || echo FAILED'
        run = run_scan_script(LIB, "sh", script, str(work))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    assert run.stdout.strip() == "FAILED", (run.stdout, run.stderr)


#: The prune clause and the full expression, as they appear in lib.sh.
PRUNE_CLAUSE = '\\\\( -type d ! -executable -fprint \\"\\$_pr.new\\" -prune \\\\)'
AMBIGUOUS_HEAD = '\\\\( -name \\"\\$_nlpat\\" -o -uid $_u -o '

#: (blind copy name, exact lib.sh text, weakened text, case)
SCAN_TWINS = [
    ("prune-on-any-denial", PRUNE_CLAUSE,
     '\\\\( -type d \\\\( ! -executable -o ! -readable \\\\) -fprint \\"\\$_pr.new\\" -prune \\\\)',
     "searchable-not-readable"),
    ("prune-every-directory", PRUNE_CLAUSE,
     '\\\\( -type d -fprint \\"\\$_pr.new\\" -prune \\\\)', "survivor-beside-pruned"),
    ("write-without-search-counted", PRUNE_CLAUSE + ' -o \\\\( \\"\\$@\\" \\\\) -print"',
     '\\\\( \\"\\$@\\" \\\\) -print -o ' + PRUNE_CLAUSE + '"', "write-without-search"),
    ("pruned-dirs-unrecorded", 'cat "$_pr.new" >>"$_pr" || return 1', ":", "image-shape"),
    ("ambiguity-ignored", '[ ! -s "$_pr.amb" ] || return 1', ":", "probe-owned-unsearchable"),
    ("ownership-unchecked", AMBIGUOUS_HEAD, '\\\\( -name \\"\\$_nlpat\\" -o ',
     "probe-owned-unsearchable"),
    ("newline-name-unchecked", AMBIGUOUS_HEAD, '\\\\( -uid $_u -o ', "newline-name"),
]


@needs_root_drop
@pytest.mark.parametrize(("blind", "old", "new", "case"), SCAN_TWINS,
                         ids=[t[0] for t in SCAN_TWINS])
def test_scan_blind_twin_is_caught(tmp_path: Path, blind: str, old: str, new: str,
                                   case: str) -> None:
    source = LIB.read_text()
    assert source.count(old) == 1, "the mutation anchor moved; update the blind twin"
    mutated = tmp_path / "lib.sh"
    mutated.write_text(source.replace(old, new))
    assert run_scan(LIB, case, "sh") == scan_expected(case)
    assert run_scan(mutated, case, "sh") != scan_expected(case), blind


@needs_root_drop
def test_scan_exclusion_twin_is_caught(tmp_path: Path) -> None:
    old = 'for _e in $_ex; do set -- \\( -path "$_e" -prune \\) -o "$@"; done'
    source = LIB.read_text()
    assert source.count(old) == 1, "the mutation anchor moved; update the blind twin"
    mutated = tmp_path / "lib.sh"
    mutated.write_text(source.replace(old, ":"))
    assert run_append(LIB) == ["rc=0", "PRUNED a/n", "PRUNED b/n"]
    assert run_append(mutated)[0] != "rc=0"


#: (case, scan output, expected INFO stdout, expected status, expected head)
REPORT_CASES = {
    "counts-only": ("0 0 0 0", "", 0, "0 0 0 0"),
    "pruned-lines": ("1 0 1 0\nPRUNED /root\nPRUNED-W /var/spool x",
                     ("INFO pruned clean /root unsearchable\n"
                      "INFO pruned clean /var/spool x unsearchable writable-without-search\n"),
                     0, "1 0 1 0"),
    "scrubbed": ("0 0\nPRUNED /a\x1b[31mb", "INFO pruned clean /a?[31mb unsearchable\n", 0, "0 0"),
    "stray-line": ("0 0\nPRUNED /root\nARM clean CONFIRMED_NEGATIVE",
                   "INFO pruned clean /root unsearchable\n", 1, "0 0"),
    "bare-tag": ("0 0\nPRUNED", "", 1, "0 0"),
    "relative-path": ("0 0\nPRUNED root", "", 1, "0 0"),
    "indented-tag": ("0 0\n PRUNED /root", "", 1, "0 0"),
    "many": ("0 0\n" + "\n".join(f"PRUNED /d{n}" for n in range(70)),
             "".join(f"INFO pruned clean /d{n} unsearchable\n" for n in range(64))
             + "INFO pruned clean truncated 70\n", 0, "0 0"),
}


def report_run(lib: Path, out: str) -> tuple[str, int, str]:
    script = ('. "$1"; rc=0; scan_report clean "$2" || rc=$?;'
              ' printf "rc=%s head=%s\\n" "$rc" "$SCAN_HEAD"')
    run = subprocess.run(["sh", "-eu", "-c", script, "sh", str(lib), out],
                         capture_output=True, text=True, env={"PATH": "/usr/bin:/bin",
                                                              "LC_ALL": "C"},
                         check=False, timeout=30)
    assert run.returncode == 0 and not run.stderr, run.stderr
    body, _, last = run.stdout.rstrip("\n").rpartition("\n")
    rc, head = last.split(" ", 1)
    return (body + "\n" if body else "", int(rc[3:]), head[5:])


@needs_sh
@pytest.mark.parametrize("case", sorted(REPORT_CASES))
def test_scan_report_case(case: str) -> None:
    out, info, rc, head = REPORT_CASES[case]
    assert report_run(LIB, out) == (info, rc, head)


REPORT_TWINS = [
    ("stray-lines-accepted", "        { bad = 1 }\n", "        { }\n", "stray-line"),
    ("tags-loosely-matched", '/^PRUNED \\// || /^PRUNED-W \\// {', '/PRUNED/ {', "relative-path"),
    ("pruned-list-unbounded", "if (n <= 64) {", "if (1) {", "many"),
    ("pruned-path-unscrubbed", 'gsub(/[^ -~]/, "?", p)', "p = p", "scrubbed"),
]


@needs_sh
@pytest.mark.parametrize(("blind", "old", "new", "case"), REPORT_TWINS,
                         ids=[t[0] for t in REPORT_TWINS])
def test_scan_report_blind_twin_is_caught(tmp_path: Path, blind: str, old: str, new: str,
                                          case: str) -> None:
    source = LIB.read_text()
    assert source.count(old) == 1, "the mutation anchor moved; update the blind twin"
    mutated = tmp_path / "lib.sh"
    mutated.write_text(source.replace(old, new))
    out, info, rc, head = REPORT_CASES[case]
    assert report_run(LIB, out) == (info, rc, head)
    assert report_run(mutated, out) != (info, rc, head), blind
