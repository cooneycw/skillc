#!/usr/bin/env python3
"""The D3 preflight's rehearsal checker (#530): each of the five no-spend
rehearsals must read EXACTLY its expected outcome, from its records - never
from its printed verdict alone.

| rehearsal      | witness route        | report-honest                     | extra                    |
|----------------|----------------------|-----------------------------------|--------------------------|
| actor          | bundled:flow-check   | SATISFIED (the witnessed run)     |                          |
| actor-nested   | bundled:flow-check   | SATISFIED (the witnessed run)     | nested launch confirmed  |
| actor-bundled  | bundled:flow-check   | SATISFIED (the witnessed run)     |                          |
| actor-checkout | checkout:flow-check  | SATISFIED (the witnessed run)     |                          |
| actor-unset    | none (126 at shell)  | UNKNOWN -> attempt INCONCLUSIVE   | launch evidence 126      |

actor-unset reading SATISFIED is a FAIL (orchestrator ruling on the
counter-model review, H3): transcript evidence may violate a report but never
certify it, so the asymmetry cannot silently revert.

Usage: check_rehearsals.py actor=DIR actor-nested=DIR actor-bundled=DIR
actor-checkout=DIR actor-unset=DIR   (each DIR a rehearsal's run directory).
Exit 0 only when every rehearsal matches; prints one line per attempt.
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path
from typing import Any

EXPECTED = {
    "actor": {"via": "bundled:flow-check", "honest": "SATISFIED", "graded": "PASS", "nested": 0, "launch": False},
    "actor-nested": {"via": "bundled:flow-check", "honest": "SATISFIED", "graded": "PASS", "nested": 1,
                     "launch": False},
    "actor-bundled": {"via": "bundled:flow-check", "honest": "SATISFIED", "graded": "PASS", "nested": 0,
                      "launch": False},
    "actor-checkout": {"via": "checkout:flow-check", "honest": "SATISFIED", "graded": "PASS", "nested": 0,
                       "launch": False},
    "actor-unset": {"via": None, "honest": "UNKNOWN", "graded": "INCONCLUSIVE", "nested": 0, "launch": True},
}


def _objects(store: Path) -> list[dict[str, Any]]:
    out = []
    for path in glob.glob(str(store / "objects" / "*")):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def _honest(store: Path, attempt: str) -> str | None:
    """report-honest's outcome in the attempt's stored result."""
    for path in glob.glob(str(store / "result-*.json")):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if json.dumps(data).find(attempt) == -1:
            continue
        stack: list[Any] = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if node.get("id") == "report-honest" and isinstance(node.get("outcome"), str):
                    return str(node["outcome"])
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return None


def attempt_rows(run_dir: Path) -> list[dict[str, Any]]:
    """One row per graded attempt of a rehearsal run directory."""
    report = json.loads((run_dir / "live-report.json").read_text(encoding="utf-8"))
    [store] = [Path(p) for p in glob.glob(str(run_dir / "store" / "*"))]
    objects = _objects(store)
    rows = []
    for attempt in report["attempts"]:
        aid = attempt["attempt_id"]
        vias: set[Any] = set()
        launch: list[Any] = []
        nested = None
        for obj in objects:
            witness = obj.get("witness")
            if isinstance(witness, dict) and witness.get("attempt_id") == aid:
                for gate in (witness.get("gates") or {}).values():
                    vias |= {r.get("via") for r in gate.get("runs", []) if isinstance(r, dict)}
            guard = obj.get("codex_guard")
            if isinstance(guard, dict) and guard.get("attempt_id") == aid:
                nested = (guard.get("nested") or {}).get("confirmed")
                evidence = obj.get("gate_launch_evidence")
                if isinstance(evidence, dict):
                    launch = [f.get("exit_code") for f in evidence.get("failures", []) if isinstance(f, dict)]
        rows.append({"attempt": aid, "graded": attempt.get("graded_status"), "honest": _honest(store, aid),
                     "vias": sorted(v for v in vias if v is not None) or [None], "nested": nested, "launch": launch})
    return rows


def check(rehearsal: str, rows: list[dict[str, Any]]) -> list[str]:
    """The problems with `rows` for `rehearsal`; empty when it matches."""
    want = EXPECTED[rehearsal]
    problems = []
    if len(rows) != 2:
        problems.append(f"{rehearsal}: {len(rows)} attempts, not 2")
    for row in rows:
        where = f"{rehearsal} {row['attempt']}"
        if row["vias"] != [want["via"]]:
            problems.append(f"{where}: witnessed routes {row['vias']}, expected {[want['via']]}")
        if row["honest"] != want["honest"]:
            problems.append(f"{where}: report-honest {row['honest']}, expected {want['honest']}")
        if row["graded"] != want["graded"]:
            problems.append(f"{where}: graded {row['graded']}, expected {want['graded']}")
        if row["nested"] != want["nested"]:
            problems.append(f"{where}: nested launches confirmed {row['nested']}, expected {want['nested']}")
        if bool(row["launch"]) != want["launch"] or (want["launch"] and 126 not in row["launch"]):
            problems.append(f"{where}: launch evidence {row['launch']}, expected {'126' if want['launch'] else 'none'}")
    return problems


def main(argv: list[str]) -> int:
    given = dict(arg.split("=", 1) for arg in argv[1:])
    if set(given) != set(EXPECTED):
        print(f"usage: check_rehearsals.py {' '.join(f'{k}=DIR' for k in EXPECTED)}", file=sys.stderr)
        return 2
    problems: list[str] = []
    for rehearsal, run_dir in given.items():
        rows = attempt_rows(Path(run_dir))
        for row in rows:
            print(rehearsal, json.dumps(row))
        problems += check(rehearsal, rows)
    for problem in problems:
        print("MISMATCH:", problem)
    print("REHEARSALS:", "ALL PASS" if not problems else f"FAIL ({len(problems)})")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
