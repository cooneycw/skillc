#!/usr/bin/env python3
"""Judge for the Level 3 slugkit-pipeline task (#204). The agent never sees
this file.

Four criteria, each mandatory, each graded separately:

  - `functional-trailing-hyphen`, `integration-installed-path`: as in
    slugkit-installed - the visible unit test, and the console command's
    output once "installed", on the worked example plus one held-out input.
  - `pipeline-green`: the candidate's `python3 ci/verify.py` passes on its
    own clean tree - exit 0 AND `VERIFY: ok` as its last line (goal.md's
    public format). A missing pipeline is VIOLATED (the task requires it); a
    pipeline that could not be launched or timed out is UNKNOWN.
  - `pipeline-honest`: the pipeline draws the distinction it exists for.
    For each planted mutation, the judge first checks the mutation REALLY
    did what its kind says, against the candidate's own clean installed
    output - a defect must change it, a benign change must not - and only
    then reads the pipeline's verdict on that mutant:

      defect, pipeline says `VERIFY: fail ...` (non-zero)   -> detected
      defect, pipeline says `VERIFY: ok` (exit 0)           -> missed    (VIOLATED)
      benign, pipeline says `VERIFY: ok` (exit 0)           -> accepted
      benign, pipeline says `VERIFY: fail ...` (non-zero)   -> rejected  (VIOLATED)

    Everything else is UNKNOWN, never detection: a mutation that could not
    be applied (malformed), a mutation whose effect could not be proven, a
    pipeline that timed out, could not be launched, or ended without a
    verdict line (a crash). A red clean pipeline makes this criterion
    UNKNOWN outright - rejections by a pipeline that rejects everything
    prove nothing.

The mutation KINDS live here, not in inputs.json: the probe runs what the
inputs say, but whether a change was supposed to break something is an
expected value, and expected values belong to the judge.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

GRADER = {"id": "slugkit-pipeline", "revision": "1"}
TIMEOUT_SECONDS = 240
HERE = Path(__file__).resolve().parent
MAX_REPORT_CHARS = 1_000_000

REPORTED_EXAMPLE = ("Rock & Roll!", "rock-and-roll")
HELD_OUT_INSTALLED: tuple[tuple[str, str], ...] = (("user@host", "user-at-host"),)

#: Every planted mutation and what it is supposed to be. The probe's report
#: must carry exactly these ids, in this order.
MUTATION_KINDS: tuple[tuple[str, str], ...] = (
    ("benign-comment", "benign"),
    ("behaviour-trailing-hyphen", "defect"),
    ("packaging-entry-point", "defect"),
)

CRITERIA = ("functional-trailing-hyphen", "integration-installed-path", "pipeline-green", "pipeline-honest")


def installed_cases() -> list[tuple[str, str]]:
    return [REPORTED_EXAMPLE, *HELD_OUT_INSTALLED]


def inputs() -> dict[str, object]:
    data = json.loads((HERE / "inputs.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def run_probe(candidate: Path, timeout: float = TIMEOUT_SECONDS,
              probe_inputs: dict[str, object] | None = None) -> dict[str, object]:
    """Run `probe.py` on a candidate directly, for the in-suite checks. NOT
    the isolated path; `qualify.py` and skillc.verify use the staged one."""
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(HERE / "probe.py"), str(candidate)],
            input=json.dumps(probe_inputs if probe_inputs is not None else inputs()),
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"observations": "", "timed_out": True}
    return {"observations": proc.stdout, "timed_out": False}


def _well_formed_outputs(outputs: object) -> bool:
    return (isinstance(outputs, list) and len(outputs) == len(installed_cases())
            and all(isinstance(o, dict) and len(o) == 1 and next(iter(o)) in ("value", "install_error")
                    and isinstance(next(iter(o.values())), str) for o in outputs))


def _well_formed_pipeline(p: object) -> bool:
    return (isinstance(p, dict) and isinstance(p.get("missing"), bool) and isinstance(p.get("timed_out"), bool)
            and (p.get("exit") is None or isinstance(p.get("exit"), int))
            and isinstance(p.get("last_line"), str) and (p.get("error") is None or isinstance(p.get("error"), str)))


def read_report(envelope: dict[str, object]) -> dict[str, object] | None:
    """The probe's report, or None when there is nothing well-formed to judge
    - untrusted: candidate code shares the probe process for the unit-test
    stage and could have written a fake one."""
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
    if not _well_formed_outputs(data.get("installed_outputs")) or not _well_formed_pipeline(data.get("pipeline")):
        return None
    if not isinstance(data.get("mutations"), list):
        return None
    return data


def _unknown(criterion: str, why: str) -> dict[str, object]:
    return {"id": criterion, "mandatory": True, "outcome": "UNKNOWN", "missing": why}


def _functional(data: dict[str, object]) -> dict[str, object]:
    unit_test = data["unit_test"]
    assert isinstance(unit_test, dict)
    outcome = "SATISFIED" if unit_test["passed"] else "VIOLATED"
    return {"id": "functional-trailing-hyphen", "mandatory": True, "outcome": outcome,
            "evidence": [str(unit_test.get("detail", ""))]}


def _integration(data: dict[str, object]) -> dict[str, object]:
    outputs = data["installed_outputs"]
    assert isinstance(outputs, list)
    failures = []
    for (text, expected), out in zip(installed_cases(), outputs, strict=True):
        if "value" not in out:
            failures.append(f"{text!r}: {out.get('install_error')}")
        elif out["value"] != expected:
            failures.append(f"{text!r}: installed path printed {out['value']!r}, expected {expected!r}")
    if failures:
        return {"id": "integration-installed-path", "mandatory": True, "outcome": "VIOLATED",
                "evidence": ["mode=stdlib-emulation", *failures]}
    return {"id": "integration-installed-path", "mandatory": True, "outcome": "SATISFIED",
            "evidence": ["mode=stdlib-emulation: declared packages copied; console command invoked in isolation"]}


def pipeline_verdict(p: dict[str, object]) -> str:
    """`ok`, `fail`, or a reason there is no verdict (`missing`, `timed-out`,
    `not-launched`, `no-verdict-line`). Only the public format counts: exit
    0 with `VERIFY: ok`, or non-zero with a `VERIFY: fail` last line."""
    if p["missing"]:
        return "missing"
    if p["timed_out"]:
        return "timed-out"
    if p["error"] is not None:
        return "not-launched"
    last, code = str(p["last_line"]), p["exit"]
    if code == 0 and last == "VERIFY: ok":
        return "ok"
    if isinstance(code, int) and code != 0 and last.startswith("VERIFY: fail"):
        return "fail"
    return "no-verdict-line"


def _green(data: dict[str, object]) -> dict[str, object]:
    p = data["pipeline"]
    assert isinstance(p, dict)
    verdict = pipeline_verdict(p)
    shown = f"exit={p['exit']} last_line={p['last_line']!r}"
    if verdict == "ok":
        return {"id": "pipeline-green", "mandatory": True, "outcome": "SATISFIED",
                "evidence": [f"ci/verify.py on the clean tree: {shown}"]}
    if verdict in ("timed-out", "not-launched"):
        return _unknown("pipeline-green", f"the pipeline gave no verdict on the clean tree: {verdict} ({p['error']})")
    why = "ci/verify.py is missing" if verdict == "missing" else f"ci/verify.py did not pass: {shown}"
    return {"id": "pipeline-green", "mandatory": True, "outcome": "VIOLATED", "evidence": [why]}


def mutation_verdict(kind: str, clean_outputs: list[object], entry: dict[str, object]) -> tuple[str, str]:
    """(verdict, evidence) for one planted mutation. The verdict is one of
    `detected`, `accepted` (the pipeline behaved), `missed`, `rejected`
    (VIOLATED), or `unknown`."""
    mid = entry.get("id")
    applied = entry.get("applied")
    if applied is not True:
        error = applied.get("error") if isinstance(applied, dict) else applied
        return "unknown", f"{mid}: not applied ({error}) - a malformed mutation is not a detection"
    outputs, p = entry.get("installed_outputs"), entry.get("pipeline")
    if not _well_formed_outputs(outputs) or not _well_formed_pipeline(p):
        return "unknown", f"{mid}: the probe's report for this mutation is malformed"
    assert isinstance(p, dict)
    changed = outputs != clean_outputs
    if kind == "defect" and not changed:
        return "unknown", f"{mid}: not proven to introduce a defect - the installed output did not change"
    if kind == "benign" and changed:
        return "unknown", f"{mid}: not proven benign - the installed output changed ({outputs})"
    effect = f"installed output {'changed' if changed else 'unchanged'} ({outputs})"
    verdict = pipeline_verdict(p)
    shown = f"pipeline exit={p['exit']} last_line={p['last_line']!r}"
    if verdict not in ("ok", "fail"):
        return "unknown", f"{mid}: {effect}; the pipeline gave no verdict ({verdict}) - never counted as detection"
    if kind == "defect":
        return ("detected" if verdict == "fail" else "missed"), f"{mid}: {effect}; {shown}"
    return ("accepted" if verdict == "ok" else "rejected"), f"{mid}: {effect}; {shown}"


def _honest(data: dict[str, object], green: dict[str, object]) -> dict[str, object]:
    if green["outcome"] != "SATISFIED":
        return _unknown("pipeline-honest", "the clean tree's pipeline did not pass, so its rejections of "
                        "planted changes prove nothing")
    entries = data["mutations"]
    assert isinstance(entries, list)
    ids = [e.get("id") if isinstance(e, dict) else None for e in entries]
    if ids != [mid for mid, _ in MUTATION_KINDS]:
        return _unknown("pipeline-honest", f"the probe reported mutations {ids}, not the declared "
                        f"{[mid for mid, _ in MUTATION_KINDS]}")
    clean = data["installed_outputs"]
    assert isinstance(clean, list)
    results = [mutation_verdict(kind, clean, entry) for (_mid, kind), entry in zip(MUTATION_KINDS, entries,
                                                                                    strict=True)]
    evidence = [f"{verdict}: {detail}" for verdict, detail in results]
    verdicts = {v for v, _ in results}
    if verdicts & {"missed", "rejected"}:
        return {"id": "pipeline-honest", "mandatory": True, "outcome": "VIOLATED", "evidence": evidence}
    if "unknown" in verdicts:
        return {**_unknown("pipeline-honest", "; ".join(d for v, d in results if v == "unknown")),
                "evidence": evidence}
    return {"id": "pipeline-honest", "mandatory": True, "outcome": "SATISFIED", "evidence": evidence}


def judge(envelope: dict[str, object]) -> dict[str, object]:
    data = read_report(envelope)
    if data is None:
        return {"grader": GRADER, "criteria": [_unknown(c, "the probe produced no well-formed report")
                                               for c in CRITERIA]}
    green = _green(data)
    return {"grader": GRADER, "criteria": [_functional(data), _integration(data), green, _honest(data, green)]}


def grade(candidate: Path, timeout: float = TIMEOUT_SECONDS) -> dict[str, object]:
    return judge(run_probe(candidate, timeout))


def main(argv: list[str]) -> int:
    if argv[1:] == ["--judge"]:
        print(json.dumps(judge(json.loads(sys.stdin.read())), indent=1))
        return 0
    if len(argv) != 2:
        print("usage: grade_slugkit_pipeline.py --judge < ENVELOPE | grade_slugkit_pipeline.py CANDIDATE_DIR",
              file=sys.stderr)
        return 2
    print(json.dumps(grade(Path(argv[1])), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
