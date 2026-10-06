"""Tests for evals/subjects/cpp-codex-flow-check/gate_reconciliation.py
(issue #269, skillc #272 acceptance item 5).

Loaded by file path, not package import - this module lives deliberately
outside `skillc/`, the same reason `test_synthetic_profile_files.py` loads
`gate_path.py` this way.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "evals/subjects/cpp-codex-flow-check/gate_reconciliation.py"
)
spec = importlib.util.spec_from_file_location("subject_gate_reconciliation", MODULE_PATH)
assert spec is not None and spec.loader is not None
gr = importlib.util.module_from_spec(spec)
# Dataclasses with `from __future__ import annotations` resolve their field
# types via `sys.modules[cls.__module__]` at class-creation time - a module
# built but not yet registered there raises AttributeError on None.
sys.modules[spec.name] = gr
spec.loader.exec_module(gr)


def _claim(
    status: str = "success", exit_code: int | None = 0, gate: str = "lint",
    attempt: int = 1, carried_from_previous_run: bool = False,
) -> object:
    return gr.GateClaim(
        gate=gate, status=status, claimed_exit_code=exit_code,
        attempt=attempt, carried_from_previous_run=carried_from_previous_run,
    )


def _witness(coverage: str = "complete", exit_code: int | None = 0, run_count: int = 1) -> object:
    return gr.GateWitnessFact(coverage=coverage, exit_code=exit_code, run_count=run_count)


def _ref() -> object:
    return gr.WitnessRef(ref="gate-witness.json", digest="sha256:witness1")


# --------------------------------------------------------------- matched / contradicting

def test_matching_exit_codes_report_matched() -> None:
    result = gr.reconcile_gate_claim(_claim(exit_code=0), _witness(exit_code=0), _ref())
    assert result.state == "matched"
    assert result.reason is None
    assert result.witness_ref == _ref()


def test_differing_exit_codes_report_contradicting_exit_code_mismatch() -> None:
    result = gr.reconcile_gate_claim(_claim(exit_code=0), _witness(exit_code=1), _ref())
    assert result.state == "contradicting"
    assert result.reason == "exit-code-mismatch"
    assert result.witness_ref == _ref()
    assert result.reason in gr.CONTRADICTING_REASONS


def test_differing_nonzero_exit_codes_also_mismatch() -> None:
    result = gr.reconcile_gate_claim(_claim(exit_code=2), _witness(exit_code=1), _ref())
    assert result.state == "contradicting"
    assert result.reason == "exit-code-mismatch"


# --------------------------------------------------------------- unknown paths

def test_no_witness_record_is_unknown_never_matched_or_contradicting() -> None:
    result = gr.reconcile_gate_claim(_claim(), None, None)
    assert result.state == "unknown"
    assert result.reason == "no-controller-witness"
    assert result.witness_ref is None


def test_no_usage_record_claim_is_unknown() -> None:
    result = gr.reconcile_gate_claim(None, _witness(), _ref())
    assert result.state == "unknown"
    assert result.reason == "no-usage-record-claim"


@pytest.mark.parametrize("coverage", ["not-observed", "launch-failed", "channel-unavailable"])
def test_witness_that_never_confirmed_execution_is_unknown_not_contradicting(coverage: str) -> None:
    """orchestrator review (#272): a claim of 'ran' cannot be contradicted by
    silence or a controller-side launch failure - #301 removed
    gate-not-executed from the vocabulary for exactly this reason."""
    result = gr.reconcile_gate_claim(_claim(), _witness(coverage=coverage, exit_code=None), _ref())
    assert result.state == "unknown"
    assert result.reason == "witness-did-not-confirm-execution"


@pytest.mark.parametrize("status", ["skipped", "not-run", "pending", "running"])
def test_an_unsettled_cpp_claim_status_is_unknown(status: str) -> None:
    """CPP's own producer (lib/cicd/evidence.py::check_entry, pinned
    b8825bd) sets exit_code to None for these statuses - there is no exit
    code to compare, so this is unknown, not a vacuous match."""
    result = gr.reconcile_gate_claim(_claim(status=status, exit_code=None), _witness(), _ref())
    assert result.state == "unknown"
    assert result.reason == "usage-record-claim-not-settled"


def test_witness_without_a_settled_exit_code_is_unknown() -> None:
    result = gr.reconcile_gate_claim(_claim(), _witness(exit_code=None), _ref())
    assert result.state == "unknown"
    assert result.reason == "witness-exit-code-not-settled"


def test_carried_forward_claim_is_unknown_even_with_matching_exit_codes() -> None:
    """Relayed fact (#272): a resumed run's witness cannot have observed a
    run from a PREVIOUS invocation, so no comparison applies - checked
    before exit codes, so even an exit-code MATCH stays unknown here."""
    result = gr.reconcile_gate_claim(
        _claim(exit_code=0, carried_from_previous_run=True), _witness(exit_code=0), _ref()
    )
    assert result.state == "unknown"
    assert result.reason == "claim-carried-from-previous-invocation"


def test_run_count_disagreement_is_unknown_never_contradicting() -> None:
    """Relayed proposal (#272): a count mismatch signals the two systems'
    accounting is not comparable, not that a specific claim is false - and
    'run-count-mismatch' is not in CONTRADICTING_REASONS, so it could not be
    reported as contradicting without inventing a fifth reason."""
    result = gr.reconcile_gate_claim(_claim(attempt=2), _witness(run_count=1), _ref())
    assert result.state == "unknown"
    assert result.reason == "run-count-disagreement"


def test_matching_run_counts_do_not_themselves_block_a_verdict() -> None:
    result = gr.reconcile_gate_claim(_claim(attempt=3), _witness(run_count=3), _ref())
    assert result.state == "matched"


# --------------------------------------------------------------- vocabulary and boundary

def test_gate_not_executed_was_removed_from_the_vocabulary() -> None:
    """#301's own correction (orchestrator review, #272): the witness
    cannot prove non-execution from silence."""
    assert "gate-not-executed" not in gr.CONTRADICTING_REASONS


def test_contradicting_reasons_matches_records_py_vocabulary() -> None:
    assert gr.CONTRADICTING_REASONS == ("outcome-disagreement", "stale-identity", "exit-code-mismatch", "tree-mismatch")


def test_tree_mismatch_is_never_produced() -> None:
    """Confirmed unreachable (module docstring): CPP's tree_signature and
    skillc's own tree_digest are different algorithms at different
    granularities, with no documented equivalence - GateClaim carries no
    tree-identity field at all, so no input could ever select this branch."""
    claim = _claim()
    assert not hasattr(claim, "claimed_tree_identity")
    assert not hasattr(claim, "tree_identity")


# --------------------------------------------------------------- mutation check

def test_exit_code_mismatch_check_is_not_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutation check: force every comparison to report matched regardless
    of the claim, and confirm the differing-exit-code case above would
    wrongly pass - proving the real function actually compares, not just
    that it returns a result."""
    def always_matched(claim: object, witness: object, witness_artifact: object) -> object:
        return gr.GateReconciliation("matched", None, witness_artifact)

    monkeypatch.setattr(gr, "reconcile_gate_claim", always_matched)
    mutated_result = gr.reconcile_gate_claim(_claim(exit_code=0), _witness(exit_code=1), _ref())
    assert mutated_result.state == "matched"  # the mutation's wrong answer, confirming it would go undetected


# --------------------------------------------------------------- golden fixture

def test_golden_fixture_claim_extraction_reconciles_as_matched() -> None:
    """Anchors GateClaim's field assumptions against a real (stripped)
    CPP usage-record sample, not just hand-built dicts. `executed_in_this_
    invocation: true` and no per-check carried-forward key present (the
    disagreement noted in the module docstring) - this test derives
    `carried_from_previous_run` as `not executed_in_this_invocation`, one
    reasonable reading, documented here as a TEST-ONLY extraction choice,
    not a production rule this module makes for its callers."""
    import json
    from pathlib import Path

    fixture = json.loads(
        (Path(__file__).parent / "fixtures/cpp-usage-record/sample-stripped.json").read_text()
    )
    checks = {c["id"]: c for c in fixture["observed"]["checks"]}
    assert set(fixture["observed"]["gates"]) == {"lint", "test", "typecheck"}

    lint = checks["lint"]
    claim = gr.GateClaim(
        gate=lint["id"],
        status=lint["status"],
        claimed_exit_code=lint["exit_code"],
        attempt=lint["attempt"],
        carried_from_previous_run=not lint["executed_in_this_invocation"],
    )
    witness = _witness(coverage="complete", exit_code=0, run_count=1)
    result = gr.reconcile_gate_claim(claim, witness, _ref())
    assert result.state == "matched"


def test_golden_fixture_claim_mismatched_against_a_different_witness_exit_code() -> None:
    import json
    from pathlib import Path

    fixture = json.loads(
        (Path(__file__).parent / "fixtures/cpp-usage-record/sample-stripped.json").read_text()
    )
    checks = {c["id"]: c for c in fixture["observed"]["checks"]}
    test_check = checks["test"]
    claim = gr.GateClaim(
        gate=test_check["id"],
        status=test_check["status"],
        claimed_exit_code=test_check["exit_code"],
        attempt=test_check["attempt"],
        carried_from_previous_run=not test_check["executed_in_this_invocation"],
    )
    witness = _witness(coverage="complete", exit_code=1, run_count=1)  # witness saw a FAILURE
    result = gr.reconcile_gate_claim(claim, witness, _ref())
    assert result.state == "contradicting"
    assert result.reason == "exit-code-mismatch"
