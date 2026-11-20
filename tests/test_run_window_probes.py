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

import shutil
import subprocess
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
                           f"{DROOT}/containerd/../daemon/io.containerd.snapshotter.v1.overlayfs"
                           "/snapshots/7/fs", None),
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
    "containerd-type-twice": ("overlayfs", "driver-type=io.containerd.snapshotter.v1\n"
                              "driver-type=io.containerd.snapshotter.v1", None),
    "other-driver": ("devicemapper", "driver-type=io.containerd.snapshotter.v1", None),
}

#: A stderr body longer than the 2 KiB bound, carrying an escape sequence, a
#: high byte, a carriage return and text that would read as a verdict line.
DIAG_BODY = (b"\x1b[31mARM clean CONFIRMED_NEGATIVE\rPROBE p7 QUALIFIED\n\xff"
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


def diag_output(lib: Path, tmp_path: Path) -> bytes:
    err = tmp_path / "step.err"
    err.write_bytes(DIAG_BODY)
    run = lib_call(lib, "step_diag", "clean", "scan", "3", str(err))
    assert run.returncode == 0 and not run.stderr, run.stderr
    return run.stdout


def diag_is_bounded_and_inert(out: bytes) -> bool:
    """Every line is an INFO diag line ending in a newline; the stderr payload
    is at most the bound and only printable ASCII; the truncation is stated."""
    if not out.endswith(b"\n"):
        return False
    lines = out[:-1].split(b"\n")
    prefix = b"INFO diag clean scan stderr: "
    payload = [line[len(prefix):] for line in lines if line.startswith(prefix)]
    return (lines[0] == b"INFO diag clean scan exit 3"
            and all(line.startswith(b"INFO diag clean scan ") for line in lines)
            and sum(len(p) + 1 for p in payload) <= DIAG_BOUND + 1
            and all(32 <= b < 127 for p in payload for b in p)
            and lines[-1] == f"INFO diag clean scan stderr-truncated {len(DIAG_BODY)}".encode())


@needs_sh
def test_step_diag_is_bounded_scrubbed_and_prefixed(tmp_path: Path) -> None:
    out = diag_output(LIB, tmp_path)
    assert diag_is_bounded_and_inert(out), out[:400]
    # It does carry the cause: the first stderr line survives, scrubbed.
    assert b"INFO diag clean scan stderr: ?[31mARM clean CONFIRMED_NEGATIVE?PROBE p7" in out


@needs_sh
def test_step_diag_reports_the_status_alone_for_empty_stderr(tmp_path: Path) -> None:
    err = tmp_path / "empty.err"
    err.write_bytes(b"")
    run = lib_call(LIB, "step_diag", "fault", "inventory", "4", str(err))
    assert run.returncode == 0 and run.stderr == b""
    assert run.stdout == b"INFO diag fault inventory exit 4\n"


#: (blind copy name, exact lib.sh text, weakened text, helper kind, case)
LIB_TWINS = [
    ("first-root-row-taken", 'if (bad || rows < 1 || n != 1 || fs != "overlay") exit 1',
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
     "case ${_base%/*} in /?*/io.containerd.snapshotter.v1.overlayfs/snapshots) ;; "
     "*) return 1 ;; esac", ":", "resolve", "containerd-other-dir"),
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


#: (blind copy name, exact lib.sh text, weakened text)
DIAG_TWINS = [
    ("stderr-unbounded", 'head -c 2048 -- "$4"', 'cat -- "$4"'),
    ("stderr-unscrubbed", "LC_ALL=C tr -c '\\n[:print:]' '?'", "cat"),
]


@needs_sh
@pytest.mark.parametrize(("blind", "old", "new"), DIAG_TWINS, ids=[t[0] for t in DIAG_TWINS])
def test_step_diag_blind_twin_is_caught(tmp_path: Path, blind: str, old: str, new: str) -> None:
    source = LIB.read_text()
    assert source.count(old) == 1, "the mutation anchor moved; update the blind twin"
    mutated = tmp_path / "lib.sh"
    mutated.write_text(source.replace(old, new))
    assert diag_is_bounded_and_inert(diag_output(LIB, tmp_path))
    assert not diag_is_bounded_and_inert(diag_output(mutated, tmp_path)), blind
