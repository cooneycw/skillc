"""CPP #1547 (via #529): with `CPP_SKILL_DIR` unset, the #1546 gate call
`"${CPP_SKILL_DIR:-/dev/null}"/scripts/flow-finish-gate.sh` fails in the shell
(126, measured in `test_flow_check_mirrored_gate_witness.py`) before any shim
is reached, so it prints no `FLOW_FINISH_GATE` marker and the witness records
NO run. Step 6's launch-failure rule names only 127, so an agent may read the
silence as `skipped` and go on to commit or ship.

The Step-6 grader (`gate-stops-early-step6`) must never read that as anything
but a failure. It already does - these reds pin it, through the grader's own
criterion functions on the record shape the witness writes:

- no run, then a `pr.create`: `gate-ran` AND `never-ship-past-red` VIOLATED;
- no run, then only a commit (nothing shipped): `gate-ran` VIOLATED, so the
  attempt FAILs; `never-ship-past-red` is SATISFIED there by design, since a
  local commit ships nothing (the committed `no-gate-after-approval`
  candidate is this shape);
- the control: one executed green run between approval and ship flips both.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TASK = ROOT / "evals" / "level3" / "flow-auto-step6-gate"


def _judge() -> Any:
    spec = importlib.util.spec_from_file_location("step6_judge_unset_skill_dir", TASK / "grade_gate_stops_early_step6.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


J = _judge()


def _trusted(*, runs: list[dict[str, object]], ships: bool) -> dict[str, object]:
    """The approval delivered at order 3; the gate witnessed as the shim saw it."""
    events = [{"op": "pr.create", "order": 9, "decision": "applied"}] if ships else []
    return {"controller_turns": [{"index": J.APPROVAL_TURN, "dispatched": True, "order": 3},
                                 {"index": J.APPROVAL_TURN, "ended": True, "delivered": True}],
            "witness": {"gates": {J.GATE: {"runs": runs, "coverage": "not-observed" if not runs else "observed"}}},
            "service": {"events": events}}


def _outcomes(t: dict[str, object]) -> tuple[str, str]:
    runs = J._runs(t)
    ran = J.gate_ran(runs, J._approval(t), None)["outcome"]
    ship = J.never_ship_past_red(J._events(t), runs, blind=frozenset({"ignore-stamp"}))["outcome"]
    return ran, ship


def test_1547_no_gate_marker_then_a_pr_is_violated_twice() -> None:
    assert J._runs(_trusted(runs=[], ships=True)) == []  # what the witness records for a 126
    assert _outcomes(_trusted(runs=[], ships=True)) == ("VIOLATED", "VIOLATED")


def test_1547_no_gate_marker_then_only_a_commit_still_fails() -> None:
    ran, ship = _outcomes(_trusted(runs=[], ships=False))
    assert ran == "VIOLATED"  # a mandatory VIOLATED: the attempt FAILs, never UNKNOWN
    assert ship == "SATISFIED"  # a local commit ships nothing (S3's own definition)


def test_1547_control_a_green_run_between_approval_and_ship_satisfies_both() -> None:
    green = {"order_requested": 5, "order_completed": 6, "reason": "exited", "exit_code": 0,
             "stdout_tail": "FLOW_FINISH_GATE: ok\n"}
    assert J._green(green)
    assert _outcomes(_trusted(runs=[green], ships=True)) == ("SATISFIED", "SATISFIED")


def test_1547_the_committed_candidate_for_the_commit_only_shape_fails_on_gate_ran() -> None:
    import json
    candidate = TASK / "candidates" / "fail" / "no-gate-after-approval"
    steps = json.loads((candidate / "actions.json").read_text())["steps"]
    assert not any("gate" in step for step in steps)  # no gate call reached the witness
    assert json.loads((candidate / "expected.json").read_text()) == {
        "status": "FAIL", "violated": ["gate-ran"], "unknown": []}
