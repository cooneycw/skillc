#!/usr/bin/env python3
"""Judge for the Level 1 slug small-fix task. The agent never sees this file.

Grading is split in two (skillc.verify, docs/specs/evaluation-facility/verification.md):

  - `probe.py` runs the candidate on the inputs in `inputs.json` and reports what
    `slugify` returned. It never sees an expected output.
  - this file, the JUDGE, holds the answers. skillc runs it as
    `grade_slug.py --judge`, with the probe's report on stdin, in a fresh
    directory, and only after every process the probe started is confirmed gone.
    So no candidate code is alive to write on its stdout, the success channel.

The judge prints one JSON object - one criterion per public requirement, each
SATISFIED/VIOLATED/UNKNOWN with evidence - and exits 0. Any other exit, or no
output, is a grader failure, not a verdict on the candidate: INCONCLUSIVE.

The probe's report is untrusted: candidate code shares the probe's process and
can write it. Anything that is not a well-formed report of returned values is
read as an interface violation, never as a verdict.

`grade(CANDIDATE_DIR)` composes the two for the in-suite checks of #5, and
`grade_slug.py CANDIDATE_DIR` does the same from a shell. Neither is the
isolated path; `qualify.py` and skillc.verify use the staged one.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

GRADER = {"id": "slug-small-fix", "revision": "2"}
TIMEOUT_SECONDS = 10

#: The one development example goal.md publishes.
REPORTED_EXAMPLE = ("Hello, World!", "hello-world")

#: Held-out variations. Each exercises exactly one requirement goal.md states, so
#: none introduces a secret requirement, and each is chosen so the OTHER rules hold
#: trivially: R1 inputs have no separator run and no boundary separator, R2 and R3
#: inputs are already lowercase, R2 inputs have no boundary separator, and R3
#: inputs have no internal separator at all. A candidate
#: with one defect therefore violates exactly that rule's criterion. Non-ASCII
#: input is deliberately absent: see README.md, "Deliberately unprobed".
HELD_OUT: tuple[tuple[str, str, str], ...] = (
    ("R1", "MiXeD", "mixed"),
    ("R1", "ABC123", "abc123"),
    ("R1", "Title-Case", "title-case"),
    ("R2", "a  b", "a-b"),
    ("R2", "one -- two", "one-two"),
    ("R2", "already-clean", "already-clean"),
    ("R2", "tabs\tand\nnewlines", "tabs-and-newlines"),
    ("R2", "x_y.z", "x-y-z"),
    ("R3", "!hi", "hi"),
    ("R3", "...edge...", "edge"),
    ("R3", "-leading", "leading"),
    ("R3", "trailing-", "trailing"),
    ("R3", "!!!", ""),
    ("R3", "", ""),
)

RULES = ("R1", "R2", "R3")

HERE = Path(__file__).resolve().parent

#: Largest probe report the judge reads; a longer one is not a report of 15 values.
MAX_REPORT_CHARS = 1_000_000


def cases() -> list[tuple[str, str]]:
    """Every (input, expected) pair, the reported example first. `inputs.json` is
    exactly the inputs, in this order; tests/test_level1_slug.py checks that."""
    return [REPORTED_EXAMPLE] + [(text, want) for _, text, want in HELD_OUT]


def run_probe(candidate: Path, timeout: float = TIMEOUT_SECONDS) -> dict[str, object]:
    """Run `probe.py` on a candidate directly, for the in-suite checks of #5.

    Returns the same envelope skillc.verify hands the judge. It is NOT the isolated
    path: no disposable copy, no subreaper, no scrubbed environment.
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(HERE / "probe.py"), str(candidate)],
            input=json.dumps([text for text, _ in cases()]), capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"observations": "", "timed_out": True}
    return {"observations": proc.stdout, "timed_out": False}


def _well_formed(out: object) -> bool:
    return (isinstance(out, dict) and len(out) == 1
            and next(iter(out)) in ("value", "raised", "not_str")
            and isinstance(next(iter(out.values())), str))


def read_report(envelope: dict[str, object]) -> dict[str, object]:
    """What the candidate returned, or why there is nothing to judge.

    The report is untrusted: candidate code could have written it. Anything that is
    not exactly a list of returned values, one per input, is an interface failure.
    """
    if envelope.get("timed_out") is True:
        return {"import_error": "candidate did not finish within the probe's time limit"}
    text = envelope.get("observations")
    if not isinstance(text, str) or not text.strip():
        return {"import_error": "the probe produced no report"}
    if len(text) > MAX_REPORT_CHARS:
        return {"import_error": "the probe report is oversized"}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"import_error": "the probe report is not JSON"}
    if isinstance(data, dict) and set(data) == {"import_error"} and isinstance(data["import_error"], str):
        return data
    outputs = data.get("outputs") if isinstance(data, dict) else None
    if (not isinstance(data, dict) or set(data) != {"outputs"} or not isinstance(outputs, list)
            or len(outputs) != len(cases()) or not all(_well_formed(o) for o in outputs)):
        return {"import_error": "the probe report is malformed or short"}
    return data


def _judge(cases: list[tuple[str, str]], outputs: list[object]) -> list[str]:
    """One failure line per case the candidate got wrong."""
    failures = []
    for (text, expected), out in zip(cases, outputs, strict=True):
        assert isinstance(out, dict)
        if "value" not in out:
            detail = out.get("raised") or f"returned non-str {out.get('not_str')}"
            failures.append(f"slugify({text!r}) {detail}")
        elif out["value"] != expected:
            failures.append(f"slugify({text!r}) == {out['value']!r}, expected {expected!r}")
    return failures


def _criterion(cid: str, failures: list[str], passed_note: str) -> dict[str, object]:
    if failures:
        return {"id": cid, "mandatory": True, "outcome": "VIOLATED", "evidence": failures}
    return {"id": cid, "mandatory": True, "outcome": "SATISFIED", "evidence": [passed_note]}


def judge(envelope: dict[str, object]) -> dict[str, object]:
    """The criteria for one probe report. No candidate code runs here."""
    pairs = cases()
    data = read_report(envelope)

    if "import_error" in data:
        reason = str(data["import_error"])
        criteria: list[dict[str, object]] = [
            {"id": "R4-interface", "mandatory": True, "outcome": "VIOLATED",
             "evidence": [reason]},
        ]
        for cid in ("reported-example", *RULES):
            criteria.append({"id": cid, "mandatory": True, "outcome": "UNKNOWN",
                             "missing": f"no callable slugify to run: {reason}"})
        return {"grader": GRADER, "criteria": criteria}

    outputs = data["outputs"]
    assert isinstance(outputs, list)
    broken = [
        f"slugify({text!r}) {out.get('raised') or 'returned non-str ' + str(out.get('not_str'))}"
        for (text, _), out in zip(pairs, outputs, strict=True)
        if isinstance(out, dict) and "value" not in out
    ]
    criteria = [
        _criterion("R4-interface", broken,
                   f"imported with site-packages disabled; slugify returned a str "
                   f"for all {len(pairs)} inputs"),
        _criterion("reported-example", _judge([REPORTED_EXAMPLE], outputs[:1]),
                   f"slugify({REPORTED_EXAMPLE[0]!r}) == {REPORTED_EXAMPLE[1]!r}"),
    ]
    held = outputs[1:]
    for rule in RULES:
        picked = [
            ((text, want), out)
            for (r, text, want), out in zip(HELD_OUT, held, strict=True) if r == rule
        ]
        if not picked:
            # An unexamined requirement is unknown, never satisfied.
            criteria.append({"id": rule, "mandatory": True, "outcome": "UNKNOWN",
                             "missing": f"no held-out cases exercise {rule}"})
            continue
        criteria.append(_criterion(
            rule, _judge([c for c, _ in picked], [o for _, o in picked]),
            f"{len(picked)} held-out {rule} cases matched",
        ))
    return {"grader": GRADER, "criteria": criteria}


def grade(candidate: Path, timeout: float = TIMEOUT_SECONDS) -> dict[str, object]:
    """Probe then judge, directly. See `run_probe` for what this does not isolate."""
    return judge(run_probe(candidate, timeout))


def main(argv: list[str]) -> int:
    if argv[1:] == ["--judge"]:
        print(json.dumps(judge(json.loads(sys.stdin.read())), indent=1))
        return 0
    if len(argv) != 2:
        print("usage: grade_slug.py --judge < ENVELOPE | grade_slug.py CANDIDATE_DIR", file=sys.stderr)
        return 2
    print(json.dumps(grade(Path(argv[1])), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
