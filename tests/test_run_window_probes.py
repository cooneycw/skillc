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
- blind twins: a deliberately weakened copy of the classifier (a missing
  reading read as zero; an unreadable census ignored; a failed removal
  trusted; a write that never landed trusted; an inherited socket fd ignored)
  must NOT reproduce the committed expectation on its discriminating fixture,
  so the fixtures can tell a working classifier from a blind one;
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
    assert run.returncode == (0 if expect.rstrip().endswith("QUALIFIED") else 1)
    for line in run.stdout.splitlines():
        kind, *rest = line.split()
        assert kind in {"ARM", "PROBE"}
        if kind == "ARM":
            assert len(rest) == 2 and rest[1] in VERDICTS


@pytest.mark.parametrize("probe", NAMES)
def test_every_probe_has_a_qualified_fault_arm_and_a_red_case(probe: str) -> None:
    qualified = (FIXTURES / probe / "qualified.expect").read_text()
    assert "ARM fault OBSERVATION_FAILED" in qualified
    assert qualified.rstrip().endswith(f"PROBE {probe} QUALIFIED")
    reds = [p for p in (FIXTURES / probe).glob("*.expect") if p.stem != "qualified"]
    assert reds and all(p.read_text().rstrip().endswith("MISMATCH") for p in reds)


#: (blind copy name, file to mutate, exact original text, weakened text, probe, fixture)
BLIND_TWINS = [
    ("missing-is-zero", "lib.sh", 'if (n != 1 || v == "" || v == "ERR") exit 1; print v',
     'if (n != 1 || v == "" || v == "ERR") v = 0; print v', probe, "qualified")
    for probe in ("p1", "p4", "p5", "p7", "p8")
] + [
    ("unreadable-ignored", "p2.sh", 'u=$(rd_uint "$1" unreadable) ||', "u=0 ||", "p2", "qualified"),
    ("unreadable-ignored", "p3.sh", 'u=$(rd_uint "$1" unreadable) ||', "u=0 ||", "p3", "qualified"),
    ("failed-rm-trusted", "p6.sh", 'if [ "$ok" -ne 1 ] || [ "$b" -lt 1 ]', "if false",
     "p6", "rm-failed"),
    ("unlanded-write-trusted", "p5.sh", 'if [ "$p" -eq 1 ]; then printf', "if true; then printf",
     "p5", "write-never-landed"),
    ("socket-fd-ignored", "p8.sh", 'if [ "$s" -eq 0 ] && [ "$b" -eq 0 ] && [ "$f" -eq 0 ]',
     'if [ "$s" -eq 0 ] && [ "$b" -eq 0 ]', "p8", "inherited-socket-fd"),
]


@needs_sh
@pytest.mark.parametrize(("blind", "target", "old", "new", "probe", "case"), BLIND_TWINS,
                         ids=[f"{t[0]}-{t[4]}" for t in BLIND_TWINS])
def test_blind_twin_is_caught_by_its_fixture(tmp_path: Path, blind: str, target: str, old: str,
                                             new: str, probe: str, case: str) -> None:
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
    assert weakened.stdout != expect, f"blind twin {blind} reproduced the committed verdicts"


@needs_sh
@pytest.mark.parametrize("probe", NAMES)
def test_usage_errors_refuse_with_exit_two(tmp_path: Path, probe: str) -> None:
    unknown = subprocess.run(["sh", str(PROBES / f"{probe}.sh"), "--no-such-flag"],
                             capture_output=True, text=True, check=False, timeout=30)
    assert unknown.returncode == 2 and "REFUSED usage" in unknown.stdout
    absent = classify(PROBES / f"{probe}.sh", tmp_path / "absent.readings")
    assert absent.returncode == 2 and "REFUSED readings-unreadable" in absent.stdout
