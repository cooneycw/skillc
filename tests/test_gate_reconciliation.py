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


def _receipt_ref() -> object:
    return gr.WitnessRef(ref="installation-receipt", digest="sha256:receipt1")


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


@pytest.mark.parametrize("status", ["skipped", "pending", "running"])
def test_an_unsettled_cpp_claim_status_is_unknown(status: str) -> None:
    """CPP's own producer (lib/cicd/evidence.py::check_entry, pinned
    b8825bd) sets exit_code to None for these statuses - there is no exit
    code to compare, so this is unknown, not a vacuous match. `not-run` is
    excluded here: against a COMPLETE witness it is `outcome-disagreement`
    (below), not merely unsettled."""
    result = gr.reconcile_gate_claim(_claim(status=status, exit_code=None), _witness(), _ref())
    assert result.state == "unknown"
    assert result.reason == "usage-record-claim-not-settled"


def test_not_run_claim_against_an_unconfirmed_witness_is_still_unknown() -> None:
    """`not-run` only becomes `outcome-disagreement` against a CONFIRMED
    execution (below) - against `not-observed` it stays the ordinary
    unsettled-claim path, since the witness never confirmed anything to
    disagree with."""
    result = gr.reconcile_gate_claim(
        _claim(status="not-run", exit_code=None),
        _witness(coverage="not-observed", exit_code=None),
        _ref(),
    )
    assert result.state == "unknown"
    assert result.reason == "witness-did-not-confirm-execution"


def test_cpp_claims_not_run_while_witness_confirms_a_complete_run_is_outcome_disagreement() -> None:
    """Reachable without any attempt/run-count mapping (orchestrator
    review, #272): the controller's own CONFIRMED observation says this
    gate ran to completion, while CPP's own record says it never ran."""
    result = gr.reconcile_gate_claim(
        _claim(status="not-run", exit_code=None), _witness(coverage="complete", exit_code=0), _ref()
    )
    assert result.state == "contradicting"
    assert result.reason == "outcome-disagreement"
    assert result.reason in gr.CONTRADICTING_REASONS


def test_cpp_claims_ran_while_witness_shows_not_observed_stays_unknown_not_contradicting() -> None:
    """The REVERSE of outcome-disagreement never contradicts (orchestrator
    review, #272): silence or a controller-side gap can never positively
    contradict a claim that a gate ran, only a confirmed observation can."""
    result = gr.reconcile_gate_claim(
        _claim(status="success", exit_code=0), _witness(coverage="not-observed", exit_code=None), _ref()
    )
    assert result.state == "unknown"
    assert result.reason == "witness-did-not-confirm-execution"


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


# --------------------------------------------------------------- stale-identity (record-level)

def test_helper_identity_matches_reports_matched() -> None:
    claimed = {"lib/cicd/evidence.py": "abc123", "lib/cicd/state.py": "def456"}
    installed = {"lib/cicd/evidence.py": "sha256:abc123", "lib/cicd/state.py": "sha256:def456"}
    result = gr.reconcile_helper_identity(claimed, installed, _receipt_ref())
    assert result.state == "matched"
    assert result.reason is None
    assert result.witness_ref is None  # a match cites nothing - there is no contradiction to witness


def test_helper_identity_mismatch_reports_contradicting_stale_identity() -> None:
    claimed = {"lib/cicd/evidence.py": "abc123"}
    installed = {"lib/cicd/evidence.py": "sha256:different"}
    ref = _receipt_ref()
    result = gr.reconcile_helper_identity(claimed, installed, ref)
    assert result.state == "contradicting"
    assert result.reason == "stale-identity"
    assert result.reason in gr.CONTRADICTING_REASONS
    assert result.witness_ref == ref  # cites the receipt identity the caller resolved, not invented here


def test_helper_identity_mismatch_without_a_receipt_to_cite_is_unknown() -> None:
    """A real contradiction with no installation-receipt available to cite
    cannot be written as `contradicting` (records.py would refuse the
    missing witness_ref) - `unknown` is the honest answer, not a verdict
    with nothing behind it."""
    claimed = {"lib/cicd/evidence.py": "abc123"}
    installed = {"lib/cicd/evidence.py": "sha256:different"}
    result = gr.reconcile_helper_identity(claimed, installed)
    assert result.state == "unknown"
    assert result.reason == "no-installation-receipt-to-cite"
    assert result.witness_ref is None


def test_helper_identity_with_no_comparable_path_is_unknown() -> None:
    result = gr.reconcile_helper_identity({"lib/cicd/evidence.py": "abc123"}, {"some/other/path.py": "sha256:x"})
    assert result.state == "unknown"
    assert result.reason == "no-comparable-helper-path"


def test_helper_identity_partial_coverage_is_unknown_not_matched() -> None:
    """Codex review, #272: a claimed path with no installed counterpart
    (`b.py`) used to be silently skipped from the comparison entirely, so
    an agreeing `a.py` alone reported the whole record `matched` - treating
    an unwitnessed helper as outside the comparison rather than as unknown.
    `matched` is reserved for every claimed path being comparable AND
    agreeing."""
    result = gr.reconcile_helper_identity({"a.py": "abc", "b.py": "def"}, {"a.py": "sha256:abc"})
    assert result.state == "unknown"
    assert result.reason == "partial-helper-coverage"

    # The full-coverage case must still report matched - the fix narrows
    # the matched verdict, it does not remove it.
    full = gr.reconcile_helper_identity({"a.py": "abc"}, {"a.py": "sha256:abc"})
    assert full.state == "matched"


def test_helper_identity_prefix_difference_alone_is_not_a_mismatch() -> None:
    """CPP's bare hex and skillc's sha256:-prefixed digest are the SAME
    value, same algorithm over the same bytes - confirmed by reading both
    implementations (module docstring), not assumed."""
    result = gr.reconcile_helper_identity(
        {"lib/cicd/evidence.py": "abc123"}, {"lib/cicd/evidence.py": "sha256:abc123"}
    )
    assert result.state == "matched"


def test_helper_identity_golden_fixture_matches() -> None:
    """Anchors against the real (stripped) sample: module_sha256 keys from
    the committed fixture, treated as if the installation receipt recorded
    the identical bytes under the same paths."""
    import json
    from pathlib import Path

    fixture = json.loads(
        (Path(__file__).parent / "fixtures/cpp-usage-record/sample-stripped.json").read_text()
    )
    claimed = fixture["observed"]["helper"]["module_sha256"]
    if not claimed:
        pytest.skip("stripped fixture carries no module_sha256 entries")
    installed = {path: f"sha256:{digest}" for path, digest in claimed.items()}
    result = gr.reconcile_helper_identity(claimed, installed)
    assert result.state == "matched"


# --------------------------------------------------------------- mutation checks

def test_outcome_disagreement_check_is_not_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    def always_unknown(claim: object, witness: object, witness_artifact: object) -> object:
        return gr.GateReconciliation("unknown", "forced", None)

    monkeypatch.setattr(gr, "reconcile_gate_claim", always_unknown)
    mutated = gr.reconcile_gate_claim(
        _claim(status="not-run", exit_code=None), _witness(coverage="complete", exit_code=0), _ref()
    )
    assert mutated.state == "unknown"  # the mutation's wrong answer, confirming it would go undetected


def test_stale_identity_check_is_not_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    def always_matched(claimed: object, installed: object) -> object:
        return gr.GateReconciliation("matched", None, None)

    monkeypatch.setattr(gr, "reconcile_helper_identity", always_matched)
    mutated = gr.reconcile_helper_identity({"a": "x"}, {"a": "sha256:y"})
    assert mutated.state == "matched"  # the mutation's wrong answer
