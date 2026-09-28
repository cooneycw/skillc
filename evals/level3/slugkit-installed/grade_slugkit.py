#!/usr/bin/env python3
"""Judge for the Level 3 slugkit-installed task. The agent never sees this
file.

Two criteria, reported and graded SEPARATELY (#13's own acceptance line:
"Report functional, constraint and integration outcomes separately; a
passing unit test must not imply installed-path success"):

  - `functional-trailing-hyphen`: does the candidate's own visible unit
    test (`tests/test_core.py`) pass, run directly against the source tree?
  - `integration-installed-path`: does the candidate's console entry point
    produce the right output once "installed" (see probe.py's module
    docstring for what that means and its two modes)?

`wrong/stale-data` is the case this split exists for: its unit test
genuinely passes (the visible example needs no replacements table at all),
while its installed path is wrong on a held-out input that does.

Grading is split in two (skillc.verify, docs/specs/evaluation-facility/
verification.md): `probe.py` runs the candidate and reports observations,
never an expected value; this file holds every answer and compares, run as
`grade_slugkit.py --judge` with the probe's report on stdin, in a fresh
directory, only after every process the probe started is confirmed gone.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

GRADER = {"id": "slugkit-installed", "revision": "1"}
TIMEOUT_SECONDS = 30

#: goal.md's own worked example (uses the "&" replacement it shows, AND a
#: trailing "!" so this input alone also exercises the base trailing-hyphen
#: fix through the installed path - not merely through the unit test).
REPORTED_EXAMPLE = ("Rock & Roll!", "rock-and-roll")

#: Held out: a replacements-table entry ("@" -> "at") goal.md never shows.
#: Chosen so it only comes out right if the REAL shipped
#: `slugkit/data/replacements.json` is read - a candidate whose unit test
#: never exercises replacements at all (wrong/stale-data) still gets this
#: wrong through the installed path. See README.md's "Held-out" section.
HELD_OUT_INSTALLED: tuple[tuple[str, str], ...] = (
    ("user@host", "user-at-host"),
)

HERE = Path(__file__).resolve().parent
MAX_REPORT_CHARS = 1_000_000


def installed_cases() -> list[tuple[str, str]]:
    return [REPORTED_EXAMPLE, *HELD_OUT_INSTALLED]


def run_probe(candidate: Path, timeout: float = TIMEOUT_SECONDS) -> dict[str, object]:
    """Run `probe.py` on a candidate directly, for the in-suite checks. NOT
    the isolated path; `qualify.py` and skillc.verify use the staged one."""
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(HERE / "probe.py"), str(candidate)],
            input=json.dumps([text for text, _ in installed_cases()]),
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"observations": "", "timed_out": True}
    return {"observations": proc.stdout, "timed_out": False}


def _well_formed_output(out: object) -> bool:
    return (isinstance(out, dict) and len(out) == 1
            and next(iter(out)) in ("value", "install_error")
            and isinstance(next(iter(out.values())), str))


def read_report(envelope: dict[str, object]) -> dict[str, object] | None:
    """The probe's report, or None if there is nothing well-formed to
    judge at all - untrusted: candidate code shares the probe process for
    the unit-test stage and could have written a fake report."""
    if envelope.get("timed_out") is True:
        return None
    text = envelope.get("observations")
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_REPORT_CHARS:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    unit_test = data.get("unit_test")
    if not isinstance(unit_test, dict) or not isinstance(unit_test.get("passed"), bool):
        return None
    if data.get("install_mode") not in ("stdlib-emulation", "real-pip"):
        return None
    outputs = data.get("installed_outputs")
    if (not isinstance(outputs, list) or len(outputs) != len(installed_cases())
            or not all(_well_formed_output(o) for o in outputs)):
        return None
    return data


def judge(envelope: dict[str, object]) -> dict[str, object]:
    data = read_report(envelope)
    if data is None:
        return {"grader": GRADER, "criteria": [
            {"id": "functional-trailing-hyphen", "mandatory": True, "outcome": "UNKNOWN",
             "missing": "the probe produced no well-formed report"},
            {"id": "integration-installed-path", "mandatory": True, "outcome": "UNKNOWN",
             "missing": "the probe produced no well-formed report"},
        ]}

    unit_test = data["unit_test"]
    assert isinstance(unit_test, dict)
    if unit_test["passed"]:
        functional = {"id": "functional-trailing-hyphen", "mandatory": True, "outcome": "SATISFIED",
                      "evidence": [str(unit_test.get("detail", "tests/test_core.py passed"))]}
    else:
        functional = {"id": "functional-trailing-hyphen", "mandatory": True, "outcome": "VIOLATED",
                      "evidence": [str(unit_test.get("detail", "tests/test_core.py failed"))]}

    mode = data["install_mode"]
    outputs = data["installed_outputs"]
    assert isinstance(outputs, list)
    failures = []
    for (text, expected), out in zip(installed_cases(), outputs, strict=True):
        assert isinstance(out, dict)
        if "value" not in out:
            failures.append(f"{text!r}: {out.get('install_error')}")
        elif out["value"] != expected:
            failures.append(f"{text!r}: installed path printed {out['value']!r}, expected {expected!r}")
    if failures:
        integration = {"id": "integration-installed-path", "mandatory": True, "outcome": "VIOLATED",
                       "evidence": [f"mode={mode}", *failures]}
    else:
        integration = {"id": "integration-installed-path", "mandatory": True, "outcome": "SATISFIED",
                       "evidence": [
                           f"mode={mode}: declared package directories and package-data copied per "
                           "pyproject.toml's declared packages list; console-script target invoked in "
                           "an isolated interpreter with only the copied site dir on sys.path"
                           if mode == "stdlib-emulation" else
                           f"mode={mode}: a real, offline pip install into an isolated target directory",
                       ]}

    return {"grader": GRADER, "criteria": [functional, integration]}


def grade(candidate: Path, timeout: float = TIMEOUT_SECONDS) -> dict[str, object]:
    return judge(run_probe(candidate, timeout))


def main(argv: list[str]) -> int:
    if argv[1:] == ["--judge"]:
        print(json.dumps(judge(json.loads(sys.stdin.read())), indent=1))
        return 0
    if len(argv) != 2:
        print("usage: grade_slugkit.py --judge < ENVELOPE | grade_slugkit.py CANDIDATE_DIR", file=sys.stderr)
        return 2
    print(json.dumps(grade(Path(argv[1])), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
