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
        "snapshot": {"probes": [{}] * (1 if diffs is None else len(diffs))}, "baseline": None,
    }, indent=2)


def test_a_rollback_reads_with_its_probe_classes() -> None:
    got = dv.read_verify(1, _verify_json("rollback", reasons=["1 regression probe: smoke:calc answers 5"]))
    assert got.verdict == dv.ROLLBACK and got.has_baseline is True
    assert got.classes == {"smoke:calc answers 5": "regression"}
    assert got.reasons == ("1 regression probe: smoke:calc answers 5",)


_OK_DIFF = {"name": "service health", "kind": "health", "classification": "ok",
            "baseline_passed": True, "current_passed": True, "baseline_ms": 1.0, "current_ms": 1.0, "detail": ""}


@pytest.mark.parametrize("verdict,code", [("proceed", 0), ("review", 0)])
def test_advisory_verdicts_exit_zero(verdict: str, code: int) -> None:
    assert dv.read_verify(code, _verify_json(verdict, diffs=[_OK_DIFF])).verdict == verdict.upper()


def test_zero_probes_reviews() -> None:
    """CPP's own zero-probe outcome (and the template-shape case): REVIEW, no classes."""
    got = dv.read_verify(0, _verify_json("review", diffs=[], has_baseline=False))
    assert got.verdict == dv.REVIEW and got.classes == {}


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
    # #282 counter-model review: no evidence is not a PROCEED.
    (0, json.dumps({"verdict": "proceed"}), "no probe list"),
    (0, _verify_json("proceed", diffs=[]), "zero probes"),
    (1, _verify_json("rollback", diffs=[]), "zero probes"),
    (0, json.dumps({"verdict": "proceed", "diffs": 7}), "no probe list"),
    (0, json.dumps({"verdict": "proceed", "diffs": True}), "no probe list"),
    (0, json.dumps({"verdict": "proceed", "diffs": {"a": 1}}), "no probe list"),
    (0, json.dumps({"verdict": "proceed", "diffs": "abc"}), "no probe list"),
    (0, json.dumps({"verdict": "proceed", "diffs": [_OK_DIFF]}), "do not match"),       # no snapshot
    (0, json.dumps({"verdict": "proceed", "diffs": [_OK_DIFF],
                    "snapshot": {"probes": [{}, {}]}}), "do not match"),               # 2 ran, 1 diffed
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


def _order(saw: bool | None, done: float | None = None, started: float | None = None,
           pre: str | None = "r1") -> str:
    return dv.baseline_order(baseline_saw_intended=saw, pre_deploy_release=pre, intended="r2",
                             baseline_done=done, deploy_started=started)


def test_baseline_order_needs_a_capture_before_the_deploy() -> None:
    assert _order(None, 100.1, 100.2) == "before_deploy"
    assert _order(False, 100.1, 100.2) == "before_deploy"
    assert _order(None, 100.3, 100.2) == "after_deploy"
    assert _order(None, None, 100.2) == "unknown"
    assert _order(None, 100.1, None) == "unknown"


def test_a_failed_identity_probe_is_no_evidence_of_order() -> None:
    """#282 counter-model review: a baseline captured AFTER a deploy whose
    restart was skipped still sees the old release, so its failed identity
    probe must not read as "before"."""
    assert _order(False) == "unknown"
    assert _order(False, 100.3, 100.2) == "after_deploy"


def test_an_identity_probe_that_saw_the_intended_release_means_after() -> None:
    assert _order(True) == "after_deploy"
    assert _order(True, 100.1, 100.2) == "after_deploy"   # any evidence of "after" wins
    assert _order(True, pre="r2") == "unknown"            # it served r2 before the deploy too
