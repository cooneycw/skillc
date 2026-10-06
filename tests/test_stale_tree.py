"""Tests for the stale-tree comparison helper (#270), which performs the
comparison `gate-witness.md` §6 and `skillc/gate_witness.py` deliberately
defer: checking a gate's recorded `tree_digest_at_start` against the digest
of the tree a grader is actually looking at.

Every mutation named in a comment below was actually applied by hand against
`skillc/stale_tree.py` and confirmed to turn the adjacent test red before
being reverted - "mutation-checked" per this repo's own convention
(see e.g. `docs/specs/evaluation-facility/gate-witness.md` §8).
"""

from __future__ import annotations

from skillc.gate_witness import GateRecord, GateRunRecord, GateWitnessRecord
from skillc.stale_tree import (
    gate_run_freshness,
    last_run_is_fresh,
    run_freshness,
    stale_gates,
)

GRADED = "sha256:graded-tree"
OTHER = "sha256:some-other-tree"


def _run(digest: str, requested_at: float = 1.0) -> GateRunRecord:
    return GateRunRecord(
        requested_at=requested_at, completed_at=requested_at + 0.1, exit_code=0,
        reason="exited", tree_digest_at_start=digest, stop_confirmed=None,
    )


def _gate(*digests: str) -> GateRecord:
    runs = tuple(_run(d, requested_at=float(i)) for i, d in enumerate(digests))
    return GateRecord(coverage="complete" if runs else "not-observed", runs=runs,
                       exclusivity_asserted=False, exclusivity_basis="")


# ------------------------------------------------------------- run_freshness


def test_a_run_whose_digest_matches_the_graded_tree_is_fresh() -> None:
    # Mutation: flip `==` to `!=` in run_freshness - this assertion goes red.
    got = run_freshness(_run(GRADED), GRADED)
    assert got.fresh is True
    assert got.tree_digest_at_start == GRADED


def test_a_run_whose_digest_differs_from_the_graded_tree_is_stale() -> None:
    # Mutation: hardcode `fresh=True` in run_freshness - this assertion goes red.
    got = run_freshness(_run(OTHER), GRADED)
    assert got.fresh is False


def test_gate_run_freshness_preserves_order_over_the_full_history() -> None:
    gate = _gate(OTHER, GRADED, OTHER)
    got = gate_run_freshness(gate, GRADED)
    assert [r.fresh for r in got] == [False, True, False]


# ---------------------------------------------------------- last_run_is_fresh


def test_zero_runs_is_none_not_false() -> None:
    # Mutation: `return bool(record.runs) and ...` collapses this to False,
    # which would make a never-run gate indistinguishable from a gate that
    # ran against a stale tree - exactly the conflation the module docstring
    # says must not happen (gate_witness.py's own not-observed owns this
    # population).
    gate = _gate()
    assert last_run_is_fresh(gate, GRADED) is None


def test_a_single_stale_run_is_false() -> None:
    gate = _gate(OTHER)
    assert last_run_is_fresh(gate, GRADED) is False


def test_a_single_fresh_run_is_true() -> None:
    gate = _gate(GRADED)
    assert last_run_is_fresh(gate, GRADED) is True


def test_an_edit_then_rerun_cycle_is_judged_by_the_last_run_only() -> None:
    """The exact workflow gate_witness.py's own docstring protects: a first
    run against a since-edited tree, followed by a legitimate rerun against
    the tree actually being graded now. Mutation: read `record.runs[0]`
    instead of `record.runs[-1]` - this test goes red because the first
    run's digest (OTHER) would then decide the verdict instead of the
    second's (GRADED), permanently branding an honest edit-then-rerun cycle
    as stale. Mutation: `all(r.tree_digest_at_start == graded for r in
    record.runs)` - also goes red, because the first run never matches."""
    gate = _gate(OTHER, GRADED)
    assert last_run_is_fresh(gate, GRADED) is True


def test_a_rerun_that_drifted_away_from_the_graded_tree_is_false() -> None:
    """The mirror image: a first run that happened to match, followed by a
    second run against a tree that has since moved on. Mutation: reading
    `record.runs[0]` here would wrongly report True."""
    gate = _gate(GRADED, OTHER)
    assert last_run_is_fresh(gate, GRADED) is False


# -------------------------------------------------------------- stale_gates


def test_stale_gates_names_only_gates_whose_last_run_was_against_another_tree() -> None:
    witness = GateWitnessRecord(
        attempt_id="a-1",
        declared_gates=("lint", "typecheck", "test"),
        gates={
            "lint": _gate(GRADED),
            "typecheck": _gate(OTHER),
            "test": _gate(OTHER, GRADED),
        },
    )
    # Mutation: drop the `is False` and use `not last_run_is_fresh(...)` -
    # this test goes red because `None` (never-run) would then count as
    # falsy and be reported stale too, which the next test pins directly.
    assert stale_gates(witness, GRADED) == ("typecheck",)


def test_stale_gates_never_includes_a_gate_with_zero_runs() -> None:
    witness = GateWitnessRecord(
        attempt_id="a-1",
        declared_gates=("lint", "never-contacted"),
        gates={
            "lint": _gate(GRADED),
            "never-contacted": _gate(),
        },
    )
    # Mutation: use `last_run_is_fresh(...) is not True` instead of
    # `is False` in stale_gates - this test goes red because the
    # never-run gate's `None` would then be swept into the stale set,
    # conflating a true bypass with an honest stale rerun.
    assert stale_gates(witness, GRADED) == ()


def test_stale_gates_is_sorted_and_handles_an_empty_witness() -> None:
    witness = GateWitnessRecord(
        attempt_id="a-1",
        declared_gates=("typecheck", "lint"),
        gates={"typecheck": _gate(OTHER), "lint": _gate(OTHER)},
    )
    assert stale_gates(witness, GRADED) == ("lint", "typecheck")
    empty = GateWitnessRecord(attempt_id="a-2", declared_gates=(), gates={})
    assert stale_gates(empty, GRADED) == ()
