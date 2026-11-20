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
