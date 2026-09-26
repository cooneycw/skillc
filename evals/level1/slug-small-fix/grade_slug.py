#!/usr/bin/env python3
"""Grader for the Level 1 slug small-fix task. The agent never sees this file.

Usage: grade_slug.py CANDIDATE_DIR, where CANDIDATE_DIR holds `src/slugify.py`.

Prints one JSON object - the grader identity and one criterion per public
requirement, each SATISFIED/VIOLATED/UNKNOWN with evidence - and exits 0. Any
other exit, or no output, is a grader failure, not a verdict on the candidate;
`qualify.py` reads it as INCONCLUSIVE.

The candidate runs in a child process with a timeout, so a raise, a hang or a
missing function is recorded against the candidate. The expected outputs never
enter that process: the child only reports what `slugify` returned, and the
comparison happens here. That keeps the answers away from candidate code; it is
NOT isolation of the result channel from hostile code, which is #9's job.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

GRADER = {"id": "slug-small-fix", "revision": "1"}
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

# Runs in the child. Candidate prints go to stderr so they cannot mix with the
# report, which is written to a duplicate of the original stdout.
CHILD = r"""
import json, os, sys
report = os.fdopen(os.dup(1), "w")
os.dup2(2, 1)
sys.path.insert(0, sys.argv[1])
inputs = json.loads(sys.stdin.read())
try:
    import slugify as module
except BaseException as exc:
    report.write(json.dumps({"import_error": f"{type(exc).__name__}: {exc}"}))
    sys.exit(0)
fn = getattr(module, "slugify", None)
if not callable(fn):
    report.write(json.dumps({"import_error": "src/slugify.py defines no callable slugify"}))
    sys.exit(0)
outputs = []
for text in inputs:
    try:
        got = fn(text)
    except BaseException as exc:
        outputs.append({"raised": f"{type(exc).__name__}: {exc}"})
        continue
    if isinstance(got, str):
        outputs.append({"value": got})
    else:
        outputs.append({"not_str": repr(got)})
report.write(json.dumps({"outputs": outputs}))
"""


def run_candidate(
    candidate: Path, inputs: list[str], timeout: float = TIMEOUT_SECONDS,
) -> dict[str, object]:
    """What the candidate's slugify returned for each input, or why it could not say."""
    src = candidate / "src"
    if not (src / "slugify.py").is_file():
        return {"import_error": f"{src / 'slugify.py'} does not exist"}
    try:
        proc = subprocess.run(
            # -S: no site-packages, so R4's "standard library only" is enforced
            # by the run itself rather than inferred from a returned string.
            [sys.executable, "-I", "-S", "-B", "-c", CHILD, str(src)],
            input=json.dumps(inputs), capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"import_error": f"candidate did not finish within {timeout}s"}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        return {"import_error": f"candidate process exited {proc.returncode} without a report"}
    outputs = data.get("outputs")
    if "import_error" not in data and (
        not isinstance(outputs, list) or len(outputs) != len(inputs)
    ):
        return {"import_error": "candidate process reported a malformed or short result"}
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


def grade(candidate: Path, timeout: float = TIMEOUT_SECONDS) -> dict[str, object]:
    cases = [REPORTED_EXAMPLE] + [(text, want) for _, text, want in HELD_OUT]
    data = run_candidate(candidate, [text for text, _ in cases], timeout)

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
        for (text, _), out in zip(cases, outputs, strict=True)
        if isinstance(out, dict) and "value" not in out
    ]
    criteria = [
        _criterion("R4-interface", broken,
                   f"imported with site-packages disabled; slugify returned a str "
                   f"for all {len(cases)} inputs"),
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


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: grade_slug.py CANDIDATE_DIR", file=sys.stderr)
        return 2
    print(json.dumps(grade(Path(argv[1])), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
