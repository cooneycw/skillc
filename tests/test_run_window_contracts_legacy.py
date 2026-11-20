"""#797 A-3b1 regression guard: a declaration that does not opt in behaves
exactly as on the parent.

This module imports ONLY names that exist on the parent (A-3a): no
`run_window_contracts`. It builds each legacy declaration at runtime from the
parent's own test builders, parses it, and compares the outcome with the
committed `controls/run-window-contracts/legacy-calibration.json`. That
fixture was derived by hand from the parent's code. Run here at the PARENT it
must PASS, which shows the fixture is the parent's real behaviour; run at the
head it must PASS too, which shows A-3b1 changed nothing for these
declarations. No bytes travel through mail or a helper's output.
"""
from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

from conftest import stamp_approval
from test_calibration import ROOT, _approved
from test_calibration_discrimination_declaration import _approved as discrimination
from test_remnant_scan_declaration import data as scan_data
from test_vm_credential_window_declaration import data as window_data

from skillc import calibration

FIXTURE = ROOT / 'controls' / 'run-window-contracts' / 'legacy-calibration.json'


def _without_scan() -> dict[str, Any]:
    raw = window_data()
    del raw['remnant_scan']
    return stamp_approval(raw)


def _discrimination_with_window() -> dict[str, Any]:
    raw = discrimination()
    raw['credential_window'] = window_data()['credential_window']
    return raw


#: case -> (builder, parser)
CASES: dict[str, tuple[Callable[[], dict[str, Any]], Callable[[dict[str, Any]], Any]]] = {
    'plain': (_approved, calibration.parse_declaration),
    'remnant-scan': (scan_data, calibration.parse_declaration),
    'credential-window': (window_data, calibration.parse_declaration),
    'credential-window-without-scan': (_without_scan, calibration.parse_declaration),
    'discrimination-with-credential-window': (_discrimination_with_window,
                                              calibration.parse_discrimination_declaration),
}


def _approval_outcome(parsed: Any) -> str:
    """Only for calibration declarations: the execution gate's verdict, with
    the exact refusal text, so a change of reason or precedence shows."""
    try:
        calibration.require_approved(parsed, ROOT)
    except calibration.DeclarationRefused as exc:
        return str(exc)
    return 'ok'


def legacy_report() -> dict[str, Any]:
    report: dict[str, Any] = {}
    for name, (build, parse) in CASES.items():
        raw = build()
        before = copy.deepcopy(raw)
        try:
            parsed = parse(raw)
        except calibration.DeclarationRefused as exc:
            report[name] = {'parse': 'refused', 'reason': str(exc),
                            'input_unmutated': raw == before}
            continue
        row: dict[str, Any] = {'parse': 'ok', 'input_unmutated': raw == before,
                               'data_is_the_input': parsed.data == before}
        if parse is calibration.parse_declaration:
            row['digest_binds'] = (calibration.declaration_digest(parsed.data)
                                   == before['approval']['declaration_digest'])
            row['require_approved'] = _approval_outcome(parsed)
        report[name] = row
    return report


def test_legacy_declarations_behave_as_on_the_parent() -> None:
    observed = json.dumps(legacy_report(), sort_keys=True, indent=2) + '\n'
    assert observed == FIXTURE.read_text()
