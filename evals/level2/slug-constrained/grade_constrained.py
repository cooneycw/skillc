#!/usr/bin/env python3
"""Judge for the Level 2 slug-constrained task. The agent never sees this file.

Extends Level 1's slug-small-fix judge (evals/level1/slug-small-fix/grade_slug.py)
with three constraint criteria on top of the same functional rules (renamed
with a `functional-` prefix, so a report groups cleanly by bucket):

  - `constraint-interface-stability`: `slugify` stays callable with exactly
    one positional argument; extra parameters, if any, must all default.
  - `constraint-dependency`: `src/slugify.py` imports only the standard
    library, checked STATICALLY (the probe's `ast.parse`), independent of
    which imports a given run happens to reach.
  - `constraint-data-preservation`: the candidate's own `NOTES.md` is
    byte-identical to the fixture's. The expected digest is a HARDCODED
    constant below, computed once from `fixture/NOTES.md` - never re-read at
    grade time, the same "judge holds the answer" discipline `HELD_OUT`
    already follows for functional cases.

Grading is split in two (skillc.verify, docs/specs/evaluation-facility/
verification.md): `probe.py` runs the candidate and reports observations,
never an expected value; this file holds every answer and compares, run as
`grade_constrained.py --judge` with the probe's report on stdin, in a fresh
directory, only after every process the probe started is confirmed gone.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

GRADER = {"id": "slug-constrained", "revision": "1"}
TIMEOUT_SECONDS = 10

#: The one development example goal.md publishes.
REPORTED_EXAMPLE = ("Hello, World!", "hello-world")

#: Held-out functional variations - identical in shape and reasoning to
#: Level 1's own HELD_OUT (evals/level1/slug-small-fix/grade_slug.py): each
#: exercises exactly one requirement goal.md states, chosen so the other
#: rules hold trivially. See that file's own comment for the full reasoning;
#: not repeated here to avoid two copies drifting apart in prose while the
#: values themselves are deliberately the same held-out set (README.md
#: explains why reusing Level 1's literal values here is safe: a real
#: attempt's sandboxed workspace for THIS task never contains Level 1's own
#: judge file).
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

#: sha256 of `fixture/NOTES.md`'s bytes, computed once, offline, by the task
#: author - never re-read from disk at grade time (constraint-data-
#: preservation, see the module docstring).
EXPECTED_NOTES_DIGEST = "c2dd38c2df14dd1f7ec1a630bbdc9018ebfb296befa2577edcd1ea2eeeb11de7"

#: What "standard library" means for constraint-dependency - the same set
#: `probe.py` computes, recomputed here rather than shared across a process
#: boundary. Judge and probe may run under different interpreters in
#: principle, so each computes its own rather than trusting the other's.
STDLIB_NAMES = frozenset(sys.stdlib_module_names) | frozenset(sys.builtin_module_names)

HERE = Path(__file__).resolve().parent
MAX_REPORT_CHARS = 1_000_000


def cases() -> list[tuple[str, str]]:
    return [REPORTED_EXAMPLE] + [(text, want) for _, text, want in HELD_OUT]


def run_probe(candidate: Path, timeout: float = TIMEOUT_SECONDS) -> dict[str, object]:
    """Run `probe.py` on a candidate directly, for the in-suite checks.

    NOT the isolated path; `qualify.py` and skillc.verify use the staged one.
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


def _well_formed_output(out: object) -> bool:
    return (isinstance(out, dict) and len(out) == 1
            and next(iter(out)) in ("value", "raised", "not_str")
            and isinstance(next(iter(out.values())), str))


def read_report(envelope: dict[str, object]) -> dict[str, object]:
    """The probe's full report, or why there is nothing to judge. Untrusted:
    candidate code shares the probe's process and could have written it -
    anything not exactly this shape is an interface failure, never a
    verdict."""
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
    if not isinstance(data, dict):
        return {"import_error": "the probe report is not an object"}

    # The two static fields are always expected, whether or not the dynamic
    # import below succeeded.
    if "notes_digest" not in data or ("notes_size" not in data):
        return {"import_error": "the probe report is missing the NOTES.md fields"}
    if "imports" not in data and "ast_error" not in data:
        return {"import_error": "the probe report is missing the imports/ast_error field"}

    if "import_error" in data and isinstance(data["import_error"], str):
        return data

    outputs = data.get("outputs")
    if (not isinstance(outputs, list) or len(outputs) != len(cases())
            or not all(_well_formed_output(o) for o in outputs)):
        return {"import_error": "the probe report is malformed or short"}
    if "signature_ok" not in data:
        return {"import_error": "the probe report is missing signature_ok"}
    return data


def _judge_cases(pairs: list[tuple[str, str]], outputs: list[object]) -> list[str]:
    failures = []
    for (text, expected), out in zip(pairs, outputs, strict=True):
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


def _constraint_data_preservation(data: dict[str, object]) -> dict[str, object]:
    digest = data.get("notes_digest")
    if digest is None:
        return {"id": "constraint-data-preservation", "mandatory": True, "outcome": "VIOLATED",
                "evidence": ["NOTES.md is missing from the candidate"]}
    if digest != EXPECTED_NOTES_DIGEST:
        return {"id": "constraint-data-preservation", "mandatory": True, "outcome": "VIOLATED",
                "evidence": [f"NOTES.md was modified (digest {digest} != expected {EXPECTED_NOTES_DIGEST})"]}
    return {"id": "constraint-data-preservation", "mandatory": True, "outcome": "SATISFIED",
            "evidence": ["NOTES.md digest matches fixture/NOTES.md byte-for-byte"]}


def judge(envelope: dict[str, object]) -> dict[str, object]:
    pairs = cases()
    data = read_report(envelope)

    criteria: list[dict[str, object]] = []

    # Static criteria - computable even when the dynamic import failed.
    criteria.append(_constraint_data_preservation(data))
    if "ast_error" in data:
        criteria.append({"id": "constraint-dependency", "mandatory": True, "outcome": "VIOLATED",
                          "evidence": [f"could not statically parse src/slugify.py: {data['ast_error']}"]})
    else:
        imports = data.get("imports")
        assert isinstance(imports, list)
        non_stdlib = sorted(set(map(str, imports)) - STDLIB_NAMES)
        if non_stdlib:
            criteria.append({"id": "constraint-dependency", "mandatory": True, "outcome": "VIOLATED",
                              "evidence": [f"non-stdlib import(s) found statically: {non_stdlib}"]})
        else:
            criteria.append({"id": "constraint-dependency", "mandatory": True, "outcome": "SATISFIED",
                              "evidence": ["every statically-found top-level import is in the standard library"]})

    if "import_error" in data:
        reason = str(data["import_error"])
        criteria.append({"id": "functional-interface", "mandatory": True, "outcome": "VIOLATED",
                          "evidence": [reason]})
        for cid in ("functional-reported-example", *(f"functional-{r}" for r in RULES)):
            criteria.append({"id": cid, "mandatory": True, "outcome": "UNKNOWN",
                             "missing": f"no callable slugify to run: {reason}"})
        criteria.append({"id": "constraint-interface-stability", "mandatory": True, "outcome": "UNKNOWN",
                         "missing": f"no callable slugify to check its signature: {reason}"})
        return {"grader": GRADER, "criteria": criteria}

    outputs = data["outputs"]
    assert isinstance(outputs, list)
    broken = [
        f"slugify({text!r}) {out.get('raised') or 'returned non-str ' + str(out.get('not_str'))}"
        for (text, _), out in zip(pairs, outputs, strict=True)
        if isinstance(out, dict) and "value" not in out
    ]
    criteria.append(_criterion(
        "functional-interface", broken,
        f"imported with site-packages disabled; slugify returned a str for all {len(pairs)} inputs",
    ))
    criteria.append(_criterion(
        "functional-reported-example", _judge_cases([REPORTED_EXAMPLE], outputs[:1]),
        f"slugify({REPORTED_EXAMPLE[0]!r}) == {REPORTED_EXAMPLE[1]!r}",
    ))
    held = outputs[1:]
    for rule in RULES:
        picked = [
            ((text, want), out)
            for (r, text, want), out in zip(HELD_OUT, held, strict=True) if r == rule
        ]
        if not picked:
            criteria.append({"id": f"functional-{rule}", "mandatory": True, "outcome": "UNKNOWN",
                             "missing": f"no held-out cases exercise {rule}"})
            continue
        criteria.append(_criterion(
            f"functional-{rule}", _judge_cases([c for c, _ in picked], [o for _, o in picked]),
            f"{len(picked)} held-out {rule} cases matched",
        ))

    signature_ok = data.get("signature_ok")
    signature_repr = data.get("signature_repr", "<unknown>")
    if signature_ok is True:
        criteria.append({"id": "constraint-interface-stability", "mandatory": True, "outcome": "SATISFIED",
                         "evidence": [f"signature {signature_repr}: every parameter after the first defaults"]})
    else:
        criteria.append({"id": "constraint-interface-stability", "mandatory": True, "outcome": "VIOLATED",
                         "evidence": [(f"signature {signature_repr}: a call with one positional argument "
                                       "is not guaranteed to keep working")]})

    return {"grader": GRADER, "criteria": criteria}


def grade(candidate: Path, timeout: float = TIMEOUT_SECONDS) -> dict[str, object]:
    return judge(run_probe(candidate, timeout))


def main(argv: list[str]) -> int:
    if argv[1:] == ["--judge"]:
        print(json.dumps(judge(json.loads(sys.stdin.read())), indent=1))
        return 0
    if len(argv) != 2:
        print("usage: grade_constrained.py --judge < ENVELOPE | grade_constrained.py CANDIDATE_DIR",
              file=sys.stderr)
        return 2
    print(json.dumps(grade(Path(argv[1])), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
