"""The judge seam (#69): tiers 2 (same-model) and 3 (independent-model)
grading, behind a stdlib-only `Judge` Protocol. The deterministic tier
(`skillc/verify.py`'s `GRADING_TIER`) stays the floor and needs none of this;
this module only adds what runs WHEN a judge is configured.

THREE TIERS, OWNER-RATIFIED (issue #69, recorded in
docs/decisions/0006-grading-tiers.md): deterministic (today's grader, always
runs), same-model (the model that produced the candidate's work), and
independent (a different model, cross-client by default). They are never
averaged, weighted or overridden - `verify.grade()` records each tier's own
verdict side by side, and this module's job stops at PRODUCING one verdict
per requested tier plus the per-criterion disagreement record between
same-model and independent.

WHAT THIS MODULE DOES NOT DO. It does not call a real judge: `FakeJudge`
below is the only implementation here, built for the tests this seam exists
to make possible. A real `mcp-second-opinion` adapter is a separate module
that implements this same `Judge` Protocol - nothing here imports it, and
nothing here assumes a network is reachable. Leak-checking judge input
(`check_judge_input`) and the cost-estimate extension for judge calls both
belong here BECAUSE they apply to any judge, adapter or fake alike - never
adapter-specific.

STRICT, NEVER COERCED. "A model judge's output is schema-constrained. Every
field is validated, and a malformed response fails that criterion's grade
whole, with no partial application" (#69's own words). `parse_judge_verdict`
either returns a fully valid `JudgeCriterionVerdict` or raises
`MalformedJudgeOutput` - there is no middle ground where an invalid `outcome`
is accepted because the `evidence` field looked fine.

Stdlib only (AGENTS.md): a Judge behind this seam is required to be too, or
this module's own import would drag runtime into `skillc/`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from . import leak, records

#: The two judge tiers this module adds. `verify.GRADING_TIER` ("deterministic")
#: is the third and is never produced here - it has no Judge, ever.
SAME_MODEL_TIER = "same-model"
INDEPENDENT_TIER = "independent"
JUDGE_TIERS = (SAME_MODEL_TIER, INDEPENDENT_TIER)

#: Reused verbatim from skillc/verify.py (#69 owner ruling) so the reason
#: string cannot drift between the two writers of `verification.disagreement`.
DISAGREEMENT_UNAVAILABLE_REASON = "fewer than two judge tiers"


class JudgeUnavailable(Exception):
    """The judge cannot be reached or used right now. Always a refusal for
    THIS TIER alone - `run_tier` turns it into an `UNAVAILABLE` verdict with
    a stated reason, never a silent drop to a lower tier and never allowed to
    take another tier down with it (#69: "An unavailable judge makes only its
    own tier unavailable")."""


class MalformedJudgeOutput(Exception):
    """A judge's response for one criterion does not meet the schema. Never
    partially trusted - `run_tier` turns this into an `UNKNOWN` outcome for
    that criterion alone, stating why, rather than accepting whichever fields
    happened to validate."""


class JudgeInputLeaked(Exception):
    """Judge input carries a machine identity (#63) and was refused before
    it could leave the machine - the judge server calls external providers,
    so this is the last local checkpoint. Never sent, never a warning."""


@dataclass(frozen=True)
class JudgeDescription:
    """A judge's own identity, carried into `verification.verdicts.<tier>.judge`
    so a reader never has to guess which model produced a verdict.

    `model` is the LLM, never the program relaying to it (#12). A judge that
    reaches its model through a server (an MCP server, say) reports that
    server as `server_name`/`server_version` and leaves `model` `None` here,
    reporting the model that ANSWERED through `JudgeAnswer` instead - two
    tiers pointed at one server then still record two different models."""

    name: str
    model: str | None
    version: str | None
    server_name: str | None = None
    server_version: str | None = None


@dataclass(frozen=True)
class JudgeAnswer:
    """`Judge.evaluate`'s answer when the judge can say which model produced
    it (#12): the raw, UNTRUSTED verdict entries plus the model that answered
    this call, which can differ from any configured one (a provider falling
    back to another model). `model` is `None` when the reply did not say."""

    verdicts: Sequence[Mapping[str, object]]
    model: str | None


@dataclass(frozen=True)
class JudgeCriterionVerdict:
    """One judge's answer for one criterion - the validated form
    `parse_judge_verdict` produces, never the raw response."""

    id: str
    outcome: str
    evidence: tuple[str, ...] = ()
    missing: str | None = None


@runtime_checkable
class Judge(Protocol):
    """One judge tier's implementation. `evaluate`'s return is UNTRUSTED raw
    data - `run_tier` validates every entry through `parse_judge_verdict`
    before any of it reaches a result record."""

    def describe(self) -> JudgeDescription:
        """This judge's identity. Called once per tier run; must not raise
        `JudgeUnavailable` for a judge that can still attempt `evaluate` -
        reserve that for an actual reachability failure."""
        ...

    def evaluate(
        self, criteria: Sequence[str], goal_text: str, candidate_files: Sequence[tuple[str, bytes]]
    ) -> Sequence[Mapping[str, object]] | JudgeAnswer:
        """Judge every id in `criteria` against `goal_text` and
        `candidate_files`. Returns one raw (unvalidated) mapping per
        criterion it answered - a judge that skips a criterion silently is
        handled by `run_tier` as `UNKNOWN`, not as a `Judge` obligation.
        A judge that learns which model answered returns a `JudgeAnswer`
        carrying it; a bare sequence leaves `describe()`'s `model` standing.

        Raises `JudgeUnavailable` when the judge cannot be reached or used at
        all for this call - never returns a fabricated or partial result to
        signal that."""
        ...


def parse_judge_verdict(raw: object, criterion_id: str) -> JudgeCriterionVerdict:
    """Validate one raw judge response for `criterion_id`. Raises
    `MalformedJudgeOutput` - never returns a partially-trusted value - unless
    every field is well formed, reusing `records.py`'s own criterion
    vocabulary and "missing evidence is explicit" rule so a judge verdict is
    held to the exact same standard a deterministic one already is."""
    if not isinstance(raw, Mapping):
        raise MalformedJudgeOutput(f"criterion {criterion_id!r}: judge response is not an object")
    unknown = set(raw) - {"id", "outcome", "evidence", "missing"}
    if unknown:
        raise MalformedJudgeOutput(f"criterion {criterion_id!r}: judge response carries unknown field(s) {sorted(unknown)}")
    if raw.get("id") != criterion_id:
        raise MalformedJudgeOutput(f"criterion {criterion_id!r}: judge response names {raw.get('id')!r}")
    outcome = raw.get("outcome")
    if outcome not in records.CRITERION_OUTCOMES:
        raise MalformedJudgeOutput(
            f"criterion {criterion_id!r}: outcome {outcome!r} is not one of {list(records.CRITERION_OUTCOMES)}"
        )
    evidence_raw = raw.get("evidence", [])
    if not isinstance(evidence_raw, list) or not all(isinstance(e, str) and e for e in evidence_raw):
        raise MalformedJudgeOutput(f"criterion {criterion_id!r}: evidence is not a list of non-empty strings")
    # `missing`, when the KEY is present at all, must be a non-empty string -
    # regardless of outcome. An earlier version only checked its type on the
    # UNKNOWN path, so a garbage `missing` value riding along on a SATISFIED
    # entry (e.g. `"missing": 123`) was silently discarded rather than
    # refused (found by cross-model review) - "every field is validated"
    # means every field present, not only the ones a given outcome requires.
    if "missing" in raw and not (isinstance(raw["missing"], str) and raw["missing"]):
        raise MalformedJudgeOutput(f"criterion {criterion_id!r}: 'missing' is present but not a non-empty string")
    missing = raw.get("missing")
    if outcome in ("SATISFIED", "VIOLATED") and not evidence_raw:
        raise MalformedJudgeOutput(f"criterion {criterion_id!r}: {outcome} with no evidence")
    if outcome == "UNKNOWN" and not missing:
        raise MalformedJudgeOutput(f"criterion {criterion_id!r}: UNKNOWN with no 'missing' reason")
    return JudgeCriterionVerdict(
        id=criterion_id, outcome=outcome, evidence=tuple(evidence_raw),
        missing=missing if isinstance(missing, str) else None,
    )


def _criterion_dict(verdict: JudgeCriterionVerdict) -> dict[str, object]:
    entry: dict[str, object] = {"id": verdict.id, "outcome": verdict.outcome}
    if verdict.evidence:
        entry["evidence"] = list(verdict.evidence)
    if verdict.missing:
        entry["missing"] = verdict.missing
    return entry


def _derive_tier_status(criteria: Iterable[Mapping[str, object]]) -> str:
    """The same three-rule order `records.derive_status` documents, applied
    to a bare criteria list (every judge criterion is mandatory - a judge
    tier has no notion of an optional one today): a VIOLATED outcome yields
    FAIL, tested before UNKNOWN; any remaining UNKNOWN yields INCONCLUSIVE;
    otherwise PASS. No criteria at all is INCONCLUSIVE, never PASS."""
    outcomes = [c.get("outcome") for c in criteria]
    if not outcomes:
        return "INCONCLUSIVE"
    if any(o == "VIOLATED" for o in outcomes):
        return "FAIL"
    if any(o != "SATISFIED" for o in outcomes):
        return "INCONCLUSIVE"
    return "PASS"


def check_judge_input(
    goal_text: str, candidate_files: Sequence[tuple[str, bytes]], criteria: Sequence[str] = ()
) -> None:
    """Leak-check EVERYTHING about to leave the machine for a judge server
    (#69: "Judge inputs pass the #63 leak check before they leave the
    machine, because the server calls external providers"). Raises
    `JudgeInputLeaked` - refuses, never warns - on the first finding.

    Scans the goal text, each candidate file's CONTENT and its NAME (a
    candidate-supplied filename is transmitted too, and is exactly as
    capable of carrying a machine identity as its content - found by
    cross-model review: an earlier version scanned only content, so a
    private IP or home path spelled into a filename reached the judge
    unchecked), and every criterion id (`evaluate()`'s `criteria` argument is
    transmitted just as much as the other two). No hostname denylist is
    applied here (an empty one, matching `skillc leak-check`'s own
    unconfigured default): this checks the built-in pattern classes (home
    paths, uid/gid, private IPv4), the same ones any committed judge-input
    control can seed without a local denylist file. Candidate bytes are
    decoded permissively (`errors="replace"`), matching `skillc/leak.py`'s
    own tolerance for undecodable content: a candidate file skillc's own
    scanner cannot read is not thereby exempt from being scanned before an
    EXTERNAL judge reads it."""
    sources: list[tuple[str, str]] = [("<goal>", goal_text)]
    for name, content in candidate_files:
        sources.append((f"{name} (filename)", name))
        sources.append((name, content.decode("utf-8", errors="replace")))
    sources.extend((f"criterion id {c!r}", c) for c in criteria)
    for name, text in sources:
        findings = list(leak.scan_text(text, frozenset()))
        if findings:
            lineno, kind, detail = findings[0]
            raise JudgeInputLeaked(
                f"judge input {name!r} carries a machine-identity finding at line {lineno} "
                f"({kind}: {detail}); refused before sending"
            )


def run_tier(
    tier: str, judge: Judge, criteria: Sequence[str], goal_text: str, candidate_files: Sequence[tuple[str, bytes]]
) -> dict[str, object]:
    """Run one judge tier and return its `verification.verdicts.<tier>` entry.

    Leak-checks input BEFORE calling the judge at all - `JudgeInputLeaked`
    propagates (a refusal to grade, not a tier outcome: leaked input is a
    reason no judge call may happen, not a fact about one judge's
    availability). `JudgeUnavailable` from EITHER `describe()` or
    `evaluate()` becomes this tier's own `UNAVAILABLE` verdict; nothing else
    is affected."""
    check_judge_input(goal_text, candidate_files, criteria)
    try:
        description = judge.describe()
        answer = judge.evaluate(criteria, goal_text, candidate_files)
    except JudgeUnavailable as exc:
        return {"status": "UNAVAILABLE", "reason": str(exc), "criteria": []}
    if isinstance(answer, JudgeAnswer):
        raw_verdicts, model = answer.verdicts, answer.model
    else:
        raw_verdicts, model = answer, description.model
    # A duplicate id is ambiguous, not last-wins: two entries for the same
    # criterion let the RESPONSE ORDER decide the grade (R1 VIOLATED then
    # SATISFIED passes; reversed, it fails) - found by cross-model review.
    # `None` marks a duplicate explicitly, distinct from "never answered".
    by_id: dict[str, object | None] = {}
    duplicated: set[str] = set()
    for entry in raw_verdicts:
        entry_id = entry.get("id") if isinstance(entry, Mapping) else None
        if isinstance(entry_id, str):
            if entry_id in by_id:
                duplicated.add(entry_id)
                by_id[entry_id] = None
            else:
                by_id[entry_id] = entry
    resolved: list[dict[str, object]] = []
    for criterion_id in criteria:
        if criterion_id in duplicated:
            resolved.append({
                "id": criterion_id, "outcome": "UNKNOWN",
                "missing": "judge returned more than one response for this criterion",
            })
            continue
        raw = by_id.get(criterion_id)
        if raw is None:
            resolved.append({"id": criterion_id, "outcome": "UNKNOWN", "missing": "judge returned no verdict for this criterion"})
            continue
        try:
            verdict = parse_judge_verdict(raw, criterion_id)
        except MalformedJudgeOutput as exc:
            resolved.append({"id": criterion_id, "outcome": "UNKNOWN", "missing": f"malformed judge response: {exc}"})
            continue
        resolved.append(_criterion_dict(verdict))
    identity: dict[str, object] = {"name": description.name, "model": model, "version": description.version}
    if description.server_name is not None:
        identity["server"] = {"name": description.server_name, "version": description.server_version}
    return {
        "status": _derive_tier_status(resolved),
        "criteria": resolved,
        "judge": identity,
    }


def compute_disagreement(verdicts: Mapping[str, object]) -> dict[str, object]:
    """The per-criterion same-model-vs-independent disagreement record
    (#69). Unavailable, with `DISAGREEMENT_UNAVAILABLE_REASON`, unless BOTH
    `SAME_MODEL_TIER` and `INDEPENDENT_TIER` reported a real (non-UNAVAILABLE)
    verdict - fewer than two comparable verdicts means there is nothing to
    compare, which is a different fact from either tier disagreeing."""
    same = verdicts.get(SAME_MODEL_TIER)
    independent = verdicts.get(INDEPENDENT_TIER)
    if (
        not isinstance(same, Mapping) or not isinstance(independent, Mapping)
        or same.get("status") == "UNAVAILABLE" or independent.get("status") == "UNAVAILABLE"
    ):
        return {"available": False, "reason": DISAGREEMENT_UNAVAILABLE_REASON}
    same_criteria = same.get("criteria")
    independent_criteria = independent.get("criteria")
    same_by_id = {c["id"]: c["outcome"] for c in same_criteria if isinstance(c, Mapping)} if isinstance(same_criteria, list) else {}
    independent_by_id = {c["id"]: c["outcome"] for c in independent_criteria if isinstance(c, Mapping)} if isinstance(independent_criteria, list) else {}
    per_criterion = []
    for criterion_id in sorted(set(same_by_id) | set(independent_by_id)):
        same_outcome = same_by_id.get(criterion_id, "UNKNOWN")
        independent_outcome = independent_by_id.get(criterion_id, "UNKNOWN")
        per_criterion.append({
            "id": criterion_id,
            "same_model": same_outcome,
            "independent": independent_outcome,
            "agree": same_outcome == independent_outcome,
        })
    return {
        "available": True,
        "per_criterion": per_criterion,
        "agreement_count": sum(1 for p in per_criterion if p["agree"]),
        "disagreement_count": sum(1 for p in per_criterion if not p["agree"]),
    }


@dataclass(frozen=True)
class FakeJudge:
    """A deterministic stand-in judge for tests - #69's own acceptance
    requires "No real model call in the test suite" and this is how every
    test in this build satisfies that. `outcome` is returned for every
    criterion asked; `unavailable`, when set, makes `evaluate` (and
    `describe`) raise `JudgeUnavailable` unconditionally, simulating an
    unreachable server without a network."""

    name: str = "fake-judge"
    model: str | None = "fake-model-1"
    version: str | None = "1"
    outcome: str = "SATISFIED"
    unavailable: str | None = None

    def describe(self) -> JudgeDescription:
        if self.unavailable:
            raise JudgeUnavailable(self.unavailable)
        return JudgeDescription(name=self.name, model=self.model, version=self.version)

    def evaluate(
        self, criteria: Sequence[str], goal_text: str, candidate_files: Sequence[tuple[str, bytes]]
    ) -> Sequence[Mapping[str, object]]:
        if self.unavailable:
            raise JudgeUnavailable(self.unavailable)
        if self.outcome == "UNKNOWN":
            return [{"id": c, "outcome": "UNKNOWN", "missing": "fake judge declines to answer"} for c in criteria]
        return [{"id": c, "outcome": self.outcome, "evidence": [f"fake-judge:{c}"]} for c in criteria]
