"""Stale-tree detection against a gate-witness record (#270, following up on
`gate-witness.md` §6's deliberately deferred comparison).

`skillc/gate_witness.py` records `tree_digest_at_start` on every run - the
controller's own digest of the tree, computed immediately before that run's
`exec_in_attempt()` call - and never compares it to anything itself (§6:
"the comparison this design's acceptance wording is actually asking for
happens LATER, outside this witness ... the grading decision belongs to
#270/#271"). This module is that comparison.

GRADED-TREE DIGEST IS SUPPLIED, NEVER RE-DERIVED HERE: a caller (a grader)
already has the tree it is grading open, and digests it itself with
`materialize.tree_digest()` - the SAME algorithm production wires as
`tree_digest_fn` for the controller side (gate_witness.py's own module
docstring). This module never calls `export()`, never re-execs anything, and
defines no second digest function to agree with - a mismatched algorithm
would make every comparison here meaningless even against a genuinely
unchanged tree, so there is deliberately only one way to produce the value
either side compares.

THE LAST RUN DECIDES, NEVER THE FIRST AND NEVER "ALL OF THEM": flow-check
legitimately edits the tree and reruns a gate after fixing a failure
(gate_witness.py's own docstring, §8 red case 3) - so a gate's EARLIER runs
are SUPPOSED to carry a now-superseded digest, and grading that as staleness
would refuse the exact honest edit-then-rerun workflow this witness protects.
Only the most recent run's digest is a claim about the tree a grader is
looking at right now.

A GATE WITH ZERO RUNS IS UNKNOWN, NEVER STALE: `gate_witness.py`'s own
`GateRecord.coverage` already has a name for "nothing was ever heard about
this gate" (`not-observed`), and conflating that with "ran, but against the
wrong tree" would let a true bypass hide behind this module's verdict instead
of `gate_witness.py`'s own `NOT_CONFIRMED`/`UNKNOWN` derivation. This module
answers `None` for that population and leaves it there.
"""

from __future__ import annotations

from dataclasses import dataclass

from .gate_witness import GateRecord, GateRunRecord, GateWitnessRecord


@dataclass(frozen=True)
class RunFreshness:
    """One run's freshness against a caller-supplied graded-tree digest."""

    requested_at: float
    tree_digest_at_start: str
    fresh: bool


def run_freshness(run: GateRunRecord, graded_tree_digest: str) -> RunFreshness:
    return RunFreshness(
        requested_at=run.requested_at,
        tree_digest_at_start=run.tree_digest_at_start,
        fresh=run.tree_digest_at_start == graded_tree_digest,
    )


def gate_run_freshness(record: GateRecord, graded_tree_digest: str) -> tuple[RunFreshness, ...]:
    """Every run's freshness, in order - the full history, for a caller that
    wants more than the last-run summary below (e.g. a report that shows an
    edit-then-rerun cycle rather than just its outcome)."""
    return tuple(run_freshness(r, graded_tree_digest) for r in record.runs)


def last_run_is_fresh(record: GateRecord, graded_tree_digest: str) -> bool | None:
    """`None` when the gate has zero runs - distinct from `False` (a real run
    that happened, but against a superseded tree), exactly as
    `GateRecord.coverage` keeps `not-observed` distinct from a genuine
    result. Only the LAST run is read: see the module docstring."""
    if not record.runs:
        return None
    return record.runs[-1].tree_digest_at_start == graded_tree_digest


def stale_gates(witness: GateWitnessRecord, graded_tree_digest: str) -> tuple[str, ...]:
    """Declared gates whose last run was captured against a tree other than
    `graded_tree_digest`, sorted for determinism. A gate with zero runs is
    never included here - see the module docstring; a caller that also wants
    to know about never-run gates reads `GateRecord.coverage`/
    `execution_observed()` for that population instead of this function."""
    stale = [
        gate
        for gate, record in witness.gates.items()
        if last_run_is_fresh(record, graded_tree_digest) is False
    ]
    return tuple(sorted(stale))
