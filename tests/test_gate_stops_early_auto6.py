"""#287 auto6: the `flow-finish` witness (`/flow:auto` Step 6's bare
`flow-finish-gate.sh` call) and the `gate-stops-early-auto6` grader's wiring.

`qualify.py` certifies the grader itself (run by tests/test_qualify_scripts_run.py);
these pin the harness pieces around it: the closed-map shim, the witness
choice (with the flow-check default and the #434 fixture route unchanged),
the session's stage reader, and the finish-plan samples.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from skillc import agent_trial, stage_capture
from skillc.backend import Limits

ROOT = Path(__file__).resolve().parent.parent
TASK = ROOT / "evals/level3/gate-stops-early-auto6"
SHIMS = ROOT / "docker/trial"


def _load(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------ the shims

def test_the_flow_auto_shim_witnesses_only_the_bare_call() -> None:
    shim = _load(SHIMS / "flow-auto-gate-shim.py")
    assert shim._DECLARED_INVOCATIONS == {(): "flow-finish"}


@pytest.mark.parametrize("argv", [["--plan", "check", "--evidence", "flow-check"], ["--check-summary"], ["--plan", "finish"]])
def test_the_flow_auto_shim_refuses_any_argument_before_the_channel(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    shim = _load(SHIMS / "flow-auto-gate-shim.py")
    monkeypatch.setattr(shim, "_ask", lambda gate: pytest.fail("the channel must not be reached"))
    assert shim.main(["flow-finish-gate.sh", *argv]) == shim.EXIT_CHANNEL_FAILURE == 125


def test_the_flow_check_shim_contract_is_unchanged() -> None:
    shim = _load(SHIMS / "flow-check-gate-shim.py")
    assert shim._DECLARED_INVOCATIONS == {
        ("--plan", "check", "--evidence", "flow-check"): "flow-check-plan",
        ("--check-summary",): "flow-check-summary",
    }


# ------------------------------------------------------------ the witness choice

def test_the_default_witness_is_flow_checks_unchanged() -> None:
    for kind in (None, "flow-check"):
        assert agent_trial._gate_witness_choice(kind, None, ".claude/scripts/flow-finish-gate.sh") == (
            None, None, agent_trial._FLOW_CHECK_GATE_SHIM_SOURCE)


def test_the_fixture_route_is_unchanged() -> None:
    fixture = SimpleNamespace(gates={"project-check": ["make", "check"]}, gate_shim_source=Path("/fixture-shim.py"))
    assert agent_trial._gate_witness_choice(None, fixture, ".claude/scripts/gate") == (  # type: ignore[arg-type]
        fixture.gates, None, Path("/fixture-shim.py"))


def test_flow_finish_selects_the_flow_auto_shim_one_gate_and_the_finish_plan() -> None:
    assert agent_trial._gate_witness_choice("flow-finish", None, ".claude/scripts/flow-finish-gate.sh") == (
        {"flow-finish": ()}, {"flow-finish": "finish"}, agent_trial._FLOW_AUTO_GATE_SHIM_SOURCE)


@pytest.mark.parametrize("kind, fixture, entrypoint, match", [
    ("make-check", None, ".claude/scripts/gate", "unknown gate_witness"),
    ("flow-finish", SimpleNamespace(gates={}, gate_shim_source=Path("/x")), ".claude/scripts/gate", "fixture"),
    ("flow-finish", None, None, "needs a declared gate_entrypoint"),
])
def test_a_witness_choice_that_cannot_be_honoured_is_refused(kind: str, fixture: object, entrypoint: str | None,
                                                             match: str) -> None:
    with pytest.raises(agent_trial.HomeFileVerificationRefused, match=match):
        agent_trial._gate_witness_choice(kind, fixture, entrypoint)  # type: ignore[arg-type]


# ------------------------------------------------------- the session's stage reader

class _Recorded(Exception):
    pass


def _session_gate_witness_kwargs(monkeypatch: pytest.MonkeyPatch, **session: Any) -> dict[str, Any]:
    """What `_WitnessSession.bind_and_check` builds its GateWitness with."""
    captured: dict[str, Any] = {}

    class FakeWitness:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.channel_unavailable = False

    class Backend:
        def controller_output(self, *_a: Any, **_kw: Any) -> bytes:
            raise _Recorded

    monkeypatch.setattr(agent_trial, "GateWitness", FakeWitness)
    with pytest.raises(_Recorded):
        agent_trial._WitnessSession("a-1", Limits(timeout=5.0), **session).bind_and_check(Backend(), None)  # type: ignore[arg-type]
    return captured


def test_a_flow_finish_session_reads_the_finish_plan_from_the_real_runner_output(monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs = _session_gate_witness_kwargs(monkeypatch, gate_args={"flow-finish": ()},
                                          stage_plans={"flow-finish": "finish"})
    assert set(kwargs["declared_gates"]) == {"flow-finish"}
    assert kwargs["declared_gates"]["flow-finish"] == ["bash", "/opt/skillc-harness/flow-finish-gate.sh"]
    sample = (TASK / "stage-samples/typecheck-skipped.stdout").read_bytes()
    capture = kwargs["stage_capture"]["flow-finish"](sample, 3)
    assert capture["status"] == "captured" and capture["plan"] == "finish"
    assert capture["stages"]["typecheck"]["outcome"] == "skipped"


def test_the_default_session_keeps_flow_checks_stage_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs = _session_gate_witness_kwargs(monkeypatch)
    assert set(kwargs["declared_gates"]) == {"flow-check-plan", "flow-check-summary"}
    assert kwargs["stage_capture"] == {"flow-check-plan": stage_capture.capture_stages}


# ------------------------------------------------------------ samples and identity

def test_every_finish_plan_sample_is_read_as_the_runner_reported_it() -> None:
    manifest = json.loads((TASK / "stage-samples/samples.json").read_text(encoding="utf-8"))
    expected = {
        "all-ok": ("ok", {"lint": "passed", "test": "passed", "typecheck": "passed"}),
        "all-passed": ("warn", {"lint": "passed", "test": "passed", "typecheck": "passed"}),
        "adds-typecheck": ("warn", {"lint": "passed", "test": "passed", "typecheck": "passed"}),
        "typecheck-skipped": ("warn", {"lint": "passed", "test": "passed", "typecheck": "skipped"}),
        "lint-failed": ("fail", {"lint": "failed", "test": "not-run", "typecheck": "not-run"}),
        "test-failed": ("fail", {"lint": "passed", "test": "failed", "typecheck": "not-run"}),
        "typecheck-failed": ("fail", {"lint": "passed", "test": "passed", "typecheck": "failed"}),
    }
    assert set(manifest) == set(expected)
    for shape, (verdict, outcomes) in expected.items():
        raw = (TASK / f"stage-samples/{shape}.stdout").read_bytes()
        assert f"FLOW_FINISH_GATE: {verdict}" in raw.decode()
        capture = stage_capture.capture_stages(raw, manifest[shape]["exit_code"], plan="finish")
        assert capture["status"] == "captured", shape
        stages: Any = capture["stages"]
        assert {k: stages[k]["outcome"] for k in outcomes} == outcomes, shape


def test_the_judge_and_grader_json_name_the_same_grader_and_criteria() -> None:
    grader = json.loads((TASK / "grader.json").read_text(encoding="utf-8"))
    judge = _load(TASK / grader["judge"]["file"])
    assert judge.GRADER == {"id": grader["id"], "revision": grader["revision"]} == {"id": "gate-stops-early-auto6",
                                                                                     "revision": "1"}
    assert list(judge.CRITERIA) == grader["criteria"]
