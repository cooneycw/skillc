#!/usr/bin/env python3
"""The #287 option-1 pre-check evaluator: reads the PRE-CHECK run's
`calibration-report.json` and prints one verdict - MET, NOT_MET or UNKNOWN.

A thin wrapper. The one implementation is `skillc.calibration_run.
precheck_verdict`, which the runner ALSO applies at dispatch: a declaration
carrying `precondition` (the pilot) is refused before any container unless
`calibration-run --precondition-report` names a report whose bytes hash to the
approval's cited sha256 and which evaluates MET (orchestrator ruling (A)).

- MET: a real run of exactly the pre-check declaration (its digest, its
  scheduled population, distinct attempt ids), every attempt evaluable on
  `gate-report-honest` exactly as the runner counts it: endpoint PASS or FAIL,
  egress not ineligible. Only possible when the agent ran the witnessed
  `flow-auto-finish` gate fresh on the graded tree.
- NOT_MET: names each attempt's reason (no witnessed run, a stale run, a run
  that did not exit normally, another UNKNOWN, not graded, egress ineligible).
- UNKNOWN: the report cannot be read as that run. Never MET.

Exit codes: 0 MET, 1 NOT_MET, 2 UNKNOWN.

Usage:
    uv run python evals/calibration-287/auto6_precheck.py <run_dir>/calibration-report.json \\
        [--declaration evals/calibration-287/auto6-precheck-declaration.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from skillc import calibration
from skillc import calibration_run as cr

HERE = Path(__file__).resolve().parent
DECLARATION = HERE / "auto6-precheck-declaration.json"
REPORT_KIND = cr.DISCRIMINATION_REPORT_KIND
REASON_CATEGORIES = cr.PRECHECK_REASON_CATEGORIES


def declaration_digest(path: Path) -> str:
    return calibration.declaration_digest(json.loads(path.read_text(encoding="utf-8")))


def attempt_reason(entry: dict[str, Any], criteria: tuple[str, ...] = ("gate-report-honest",)) -> str | None:
    return cr.precheck_attempt_reason(entry, criteria)


def evaluate(report_path: Path, declaration: Path = DECLARATION) -> tuple[str, list[str]]:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        return cr.PRECHECK_UNKNOWN, [f"the report is unreadable: {exc}"]
    return cr.precheck_verdict(report, calibration.load_discrimination_declaration(declaration))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report", type=Path)
    parser.add_argument("--declaration", type=Path, default=DECLARATION)
    args = parser.parse_args(argv)
    verdict, lines = evaluate(args.report, args.declaration)
    for line in lines:
        print(f"auto6-precheck: {line}")
    print(f"AUTO6_PRECHECK: {verdict}")
    return {cr.PRECHECK_MET: 0, cr.PRECHECK_NOT_MET: 1}.get(verdict, 2)


if __name__ == "__main__":
    sys.exit(main())
