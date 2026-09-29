"""Separate functional/constraint/integration outcome reporting (issue #13).

A grader's `criteria` list already carries a per-criterion `outcome`
(`records.CRITERION_OUTCOMES`: SATISFIED/VIOLATED/UNKNOWN) - what is missing
is a way to see the THREE named dimensions #13 asks for separately, so a
passing functional criterion can never be read as implying constraint or
integration success too (#13's own acceptance line: "a passing unit test
must not imply installed-path success").

DECLARED, NEVER INFERRED (review ruling): a criterion's dimension comes only
from `verify.GraderDef.dimensions` (grader.json's own optional `dimensions`
field) - never guessed from the criterion id's own naming convention. A
convention is an instrument nobody enforces; this module trusts only what
was declared. A criterion with no declaration is `UNCLASSIFIED`, stated
plainly rather than defaulted into a bucket that looks like the others.

This module is pure - it reads a criteria list and a dimension mapping
(both already loaded elsewhere) and returns a report. It calls no grader,
runs no probe, and makes no docker/live-agent call of its own.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .verify import OUTCOME_DIMENSIONS

#: The bucket a criterion falls into when its grader declared no dimension
#: for it (or the grader itself declares no `dimensions` at all). Distinct
#: from any of `OUTCOME_DIMENSIONS` on purpose - reported, never guessed
#: into "functional" or dropped.
UNCLASSIFIED = "unclassified"

#: Every bucket this module ever reports, in a fixed, stable order -
#: `OUTCOME_DIMENSIONS` (declared, closed vocabulary) plus `UNCLASSIFIED`.
BUCKETS: tuple[str, ...] = (*OUTCOME_DIMENSIONS, UNCLASSIFIED)

#: A bucket's own verdict, mirroring `records.derive_status`'s exact rule
#: (VIOLATED-first, then no-mandatory, then any-not-SATISFIED, else PASS) -
#: scoped to one bucket's criteria instead of a whole record's. `NOT_APPLICABLE`
#: is this module's own addition: a record-level rule has no "this dimension
#: does not apply" case, because a record always has SOME criteria, but a
#: single dimension bucket can legitimately be empty (Level 1 has no
#: constraint-*/integration-* criteria at all) - reporting that as
#: INCONCLUSIVE would misread "not part of this task" as "we tried to check
#: and could not," exactly the "didn't measure" vs "nothing to measure"
#: confusion issue #158's term_forwarding docstring names for a different
#: field.
NOT_APPLICABLE = "not-applicable"
FAIL = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"
PASS = "PASS"
#: Review ruling (PR #13, PR1): distinct from `UNCLASSIFIED`. "This grader
#: declares no dimensions" (`UNCLASSIFIED`) is a true statement ABOUT THE
#: GRADER; "the dimensions lookup itself failed" (`UNAVAILABLE`) is a
#: statement about THIS CALL, and collapsing the two would let a caller
#: mistake a failed lookup for a grader that genuinely declares nothing -
#: exactly the "didn't measure" vs "nothing to measure" confusion this
#: module's own `NOT_APPLICABLE` already exists to avoid, one level up.
UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class BucketReport:
    """One dimension's slice of a graded record: its own criteria (in the
    record's original order) and the verdict they support."""

    dimension: str
    verdict: str
    criteria: tuple[Mapping[str, object], ...]


@dataclass(frozen=True)
class OutcomeReport:
    """Every bucket for one graded record, keyed by dimension name. Always
    carries all of `BUCKETS`, even ones with no criteria at all (verdict
    `NOT_APPLICABLE`) - a caller must never infer absence from a missing
    key.

    `unavailable_reason` is set only when `build`'s own dimensions lookup
    failed (see its docstring) - every bucket then reads `UNAVAILABLE`
    rather than a guessed real verdict, since criteria cannot be correctly
    attributed to a dimension without the declaration that failed to load."""

    buckets: Mapping[str, BucketReport]
    unavailable_reason: str | None = None

    def __getitem__(self, dimension: str) -> BucketReport:
        return self.buckets[dimension]

    def as_dict(self) -> dict[str, object]:
        """The JSON-safe shape `collection-run`'s and `pilot-report`'s own
        paste-backs embed - plain dict/list/str, `criteria` as plain dicts."""
        out: dict[str, object] = {
            dim: {"verdict": b.verdict, "criteria": [dict(c) for c in b.criteria]}
            for dim, b in self.buckets.items()
        }
        if self.unavailable_reason is not None:
            out["unavailable_reason"] = self.unavailable_reason
        return out


def _bucket_verdict(criteria: Sequence[Mapping[str, object]]) -> str:
    if not criteria:
        return NOT_APPLICABLE
    mandatory = [c for c in criteria if c.get("mandatory") is True]
    outcomes = [c.get("outcome") for c in mandatory]
    if "VIOLATED" in outcomes:
        return FAIL
    if not outcomes:
        return INCONCLUSIVE
    if any(o != "SATISFIED" for o in outcomes):
        return INCONCLUSIVE
    return PASS


def build(
    criteria: Sequence[Mapping[str, object]], dimensions: Mapping[str, str],
    *, unavailable_reason: str | None = None,
) -> OutcomeReport:
    """Groups `criteria` (a graded record's own `graded.criteria` list, or
    the equivalent from a ledger record) by each entry's DECLARED dimension
    (`dimensions`, e.g. `GraderDef.dimensions`) - never by inferring one
    from the criterion id. An id absent from `dimensions`, or a `dimensions`
    mapping that is empty entirely, lands that criterion in `UNCLASSIFIED`.

    `unavailable_reason`, when given, means the CALLER could not even load
    `dimensions` (a grader.json read/parse failure, say) - `dimensions` is
    then ignored entirely and every bucket reports `UNAVAILABLE`, never a
    guessed `UNCLASSIFIED`: this call does not know whether the grader
    declares dimensions or not, and must not claim it does. This is a
    caller-side distinction, not a "some criteria classified, some not"
    case - see `UNAVAILABLE`'s own module-level comment.

    Every criterion in `criteria` appears in exactly one bucket - this
    function is exhaustive and non-overlapping by construction, since each
    criterion is placed by one lookup."""
    if unavailable_reason is not None:
        return OutcomeReport(
            buckets={dim: BucketReport(dimension=dim, verdict=UNAVAILABLE, criteria=()) for dim in BUCKETS},
            unavailable_reason=unavailable_reason,
        )
    grouped: dict[str, list[Mapping[str, object]]] = {b: [] for b in BUCKETS}
    for criterion in criteria:
        cid = criterion.get("id")
        dimension = dimensions.get(cid) if isinstance(cid, str) else None
        bucket = dimension if dimension in OUTCOME_DIMENSIONS else UNCLASSIFIED
        grouped[bucket].append(criterion)
    return OutcomeReport(buckets={
        dim: BucketReport(dimension=dim, verdict=_bucket_verdict(items), criteria=tuple(items))
        for dim, items in grouped.items()
    })
