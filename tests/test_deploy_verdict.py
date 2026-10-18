"""`skillc.deploy_verdict` (#282): CPP's deploy verification read as
observations. Every reader has its UNKNOWN case beside its good one, because a
reader that cannot say UNKNOWN turns a run that observed nothing into a pass.
"""

from __future__ import annotations

import json

import pytest

from skillc import deploy_verdict as dv


def _verify_json(verdict: str, *, diffs: list[dict[str, object]] | None = None,
                 has_baseline: bool = True, reasons: list[str] | None = None) -> str:
    """The shape `lib.cicd verify --json` prints at 86641e8 (DeployVerifyResult.to_dict)."""
    return json.dumps({
        "verdict": verdict, "reasons": reasons or [], "exit_code": 1 if verdict == "rollback" else 0,
        "has_baseline": has_baseline,
        "diffs": diffs if diffs is not None else [
            {"name": "calc answers 5", "kind": "smoke", "classification": "regression",
             "baseline_passed": True, "current_passed": False, "baseline_ms": 3.0, "current_ms": 3.1, "detail": ""}],
        "snapshot": {}, "baseline": None,
    }, indent=2)


def test_a_rollback_reads_with_its_probe_classes() -> None:
    got = dv.read_verify(1, _verify_json("rollback", reasons=["1 regression probe: smoke:calc answers 5"]))
    assert got.verdict == dv.ROLLBACK and got.has_baseline is True
    assert got.classes == {"smoke:calc answers 5": "regression"}
    assert got.reasons == ("1 regression probe: smoke:calc answers 5",)


@pytest.mark.parametrize("verdict,code", [("proceed", 0), ("review", 0)])
def test_advisory_verdicts_exit_zero(verdict: str, code: int) -> None:
    assert dv.read_verify(code, _verify_json(verdict, diffs=[])).verdict == verdict.upper()


@pytest.mark.parametrize("code,stdout,why", [
    (None, _verify_json("proceed"), "no exit status"),          # timed out / never ran
    (0, "", "printed nothing"),
    (0, "Verdict: PROCEED\n", "not one JSON document"),         # the text mode, not --json
    (0, "[]", "not a JSON object"),
    (0, json.dumps({"verdict": "halt"}), "no known verdict"),
    (0, json.dumps({"diffs": []}), "no known verdict"),
    (0, _verify_json("rollback"), "contradicts"),               # CPP exits 1 for ROLLBACK
    (1, _verify_json("proceed", diffs=[]), "contradicts"),
    (2, _verify_json("review", diffs=[]), "contradicts"),       # a crash is not a verdict
    (0, _verify_json("proceed", diffs=[{"name": "x"}]), "unreadable probe diff"),
])
def test_no_established_verdict_is_unknown(code: int | None, stdout: str, why: str) -> None:
    got = dv.read_verify(code, stdout)
    assert got.verdict == dv.UNKNOWN and why in got.why_unknown


def test_health_no_checks_configured_is_never_healthy() -> None:
    """claude-power-pack#1476: the default text mode exits 0 for a config with
    no probes. Reading the exit code would call that healthy."""
    text = "Health Check: no checks configured\n\n  Configure endpoints and processes in .claude/cicd.yml:\n"
    got = dv.read_health(0, text)
    assert got.status == "no_probes" and got.status != "healthy"


@pytest.mark.parametrize("code,text,status", [
    (0, "## Health Checks\n\nResult: Health: 1/1 checks passed\n", "healthy"),
    (1, "## Health Checks\n\nResult: Health: 0/1 checks passed\n", "unhealthy"),
    (1, "Result: Health: 1/1 checks passed\n", "unknown"),    # summary and exit disagree
    (0, "Result: Health: 0/1 checks passed\n", "unknown"),
    (0, "", "unknown"),                                        # nothing printed
    (None, "Result: Health: 1/1 checks passed\n", "unknown"),  # no exit status
    (0, "Result: Health: 1/1 checks passed\nResult: Health: 1/1 checks passed\n", "unknown"),
])
def test_health_reads_the_printed_summary_against_the_exit_code(code: int | None, text: str, status: str) -> None:
    assert dv.read_health(code, text).status == status


def test_release_identity_and_served_release() -> None:
    assert dv.served_release('{"release": "r2"}') == "r2"
    for body in (None, "", "not json", "[]", '{"release": ""}', '{"release": 2}', '{"status": "ok"}'):
        assert dv.served_release(body) is None
    assert dv.release_identity("r2", "r2") == "matched"
    assert dv.release_identity("r1", "r2") == "mismatched"
    assert dv.release_identity("r2-calc-wrong", "r2") == "mismatched"
    assert dv.release_identity(None, "r2") == "unknown"


@pytest.mark.parametrize("before,after,alive,want", [
    ("10", "11", True, "restarted"),
    ("10", "10", True, "skipped"),
    ("10", "10", False, "unknown"),   # the process died: not a skipped restart
    ("10", "11", False, "unknown"),   # the new process is gone
    (None, "11", True, "unknown"),
    ("10", "11", None, "unknown"),
])
def test_restart_is_read_from_pids(before: str | None, after: str | None, alive: bool | None, want: str) -> None:
    assert dv.restart_observed(before, after, alive) == want


def _order(saw: bool | None, captured: str | None = None, started: float | None = None,
           pre: str | None = "r1") -> str:
    return dv.baseline_order(baseline_saw_intended=saw, pre_deploy_release=pre, intended="r2",
                             baseline_captured_at=captured, deploy_started=started)


def test_baseline_order_from_the_release_probe() -> None:
    assert _order(False) == "before_deploy"
    assert _order(True) == "after_deploy"          # the intended release was already served
    assert _order(None) == "unknown"
    assert _order(True, pre="r2") == "unknown"     # it served r2 before the deploy too: no evidence


def test_baseline_order_from_timestamps() -> None:
    t = "2026-10-17T21:00:00+0000"
    epoch = 1792270800.0  # that instant
    assert _order(None, t, epoch + 5) == "before_deploy"
    assert _order(None, t, epoch - 5) == "after_deploy"
    assert _order(None, t, epoch + 0.5) == "unknown"   # the same second proves nothing
    assert _order(None, "not a time", epoch + 5) == "unknown"
    # Any evidence of "after" wins over "before".
    assert _order(False, t, epoch - 5) == "after_deploy"
    assert _order(True, t, epoch + 5) == "after_deploy"
