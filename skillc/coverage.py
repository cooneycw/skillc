"""Per-skill coverage reports from retained bundles (issue #272).

Reads a bundle's own evaluation records and produces one row per (skill
path, skill version, client, task/case, arm): what happened when that skill
was tested, retaining every declared, not-run, unavailable, unknown or
flagged-coverage state rather than collapsing them into a single verdict.

THE INVENTORY SOURCE IS NOT `installation-receipt.installed[]` (orchestrator
review, #272). That list names every installed FILE - helpers, libraries and
scripts, not just skills under evaluation - so it cannot answer "what was
declared for testing". The v2 record bundle itself carries no such
declaration either: `trial-ledger.subject` is a bare `{digest}`, and the
actual selection lives in a `Profile` artifact outside the bundle (skillc
#20's own nit: a retained bundle cannot reconstruct its own inventory).

So this module takes the resolved declared-skill selection as a SEPARATE,
OPTIONAL input (`DeclaredInventory`) rather than deriving it from the
bundle. Without one, rows exist only for skills the bundle itself evidences
(`skill-evidence` entries) - there is no untested-skill inventory and no
fixed row-count assertion, and the report says so explicitly
(`inventory == "not_declared"`) rather than silently falling back to
`installation-receipt.installed`.

`skill_version` (the row key's version component) is `installation-receipt.
installed[].digest` for that path - always present, already this schema's
own per-path content identity (used identically by `_skill_evidence_binding`
and `_skill_invocation_binding`). `skill-evidence.body_digest` was
considered and rejected: it is optional, and records.md's own Q3 answer
states it is "not cross-checked against" #265's inventory, a narrower
guarantee than this row key needs.

NO PER-SKILL PASS/FAIL VERDICT (orchestrator review, #272, acceptance item
3). `verified-result.status` is ATTEMPT-level; copying it onto every skill
row credits every loaded skill with the same outcome, exactly what item 3
forbids. Each row instead carries the attempt's outcome ALONGSIDE this
skill's own lifecycle facts (`execution_observed`, `read_observed`) and its
OWNED criteria (`criteria_owned`, shared-marked) - never reduced to one
verdict.

OUTCOMES PARTITION; COVERAGE FLAGS DO NOT (orchestrator review, #272).
`outcomes` (`PASS`/`FAIL`/`NOT_RUN`/`UNAVAILABLE`/`UNKNOWN`) sum to a row's
own `scheduled` count - every scheduled attempt lands in exactly one.
`coverage_flags` (`missing-transcript`, `unmatched-invocation`) are
orthogonal: a `PASS` attempt can still carry `missing-transcript`. Counting
them inside `outcomes` would double-count the denominator.

REFUSES BEFORE REPORTING (orchestrator review, #272, acceptance item 6).
`assemble_coverage_report` runs the bundle's own validation rules first and
raises `CoverageRefused`, naming the failing rule(s), rather than relying on
a caller having validated already - a duplicate, forged-status or
altered-artifact bundle is refused here even if nobody checked it first.

WIRING THE GATE RECONCILER AND THE DISCRIMINATION/IMPROVEMENT EVALUATORS
(orchestrator review, #269/#272). This module NEVER imports `evals/
subjects/cpp-codex-flow-check/gate_reconciliation.py` - that would put
CPP-specific knowledge back inside `skillc/`, exactly what relocating it
there was for. What this module DOES: expose every `skill-evidence.
external_evidence.reconciliation` value a bundle already carries
(`reconciliation_counts` on each row) - the reconciler's OUTPUT, already
written into the bundle by whatever assembler produced it, never
re-decided here. `evaluate_discrimination`/`evaluate_improvement`
(`skillc/reliability.py`) are genuinely subject-agnostic statistics, so
THOSE are called directly: `case_pairs` on the report computes a
DISCRIMINATING/NOT_SHOWN/UNKNOWN verdict for every certified `case.arm`
pairing in the bundle (#273's own `case-pairing` bundle rule already
guarantees reciprocity/uniqueness by the time refuse-before-reporting lets
a bundle through, so "certified" is unconditional here), with the per-arm
pass/evaluable counts kept BESIDE the verdict, never replaced by it.
`compute_improvement` is a thin passthrough to `reliability.
evaluate_improvement` for a caller that has its OWN CPP-vs-baseline
(`config.arm`) counts - `config.arm` is explicitly NOT a validated field in
`skillc/records.py` (records.md: "remain outside this document's validated
fields"), so this module does not invent a discovery convention for it the
way it does for `case.arm`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from . import checks, records
from . import reliability as rel

OUTCOMES = ("PASS", "FAIL", "NOT_RUN", "UNAVAILABLE", "UNKNOWN")
COVERAGE_FLAGS = ("missing-transcript", "unmatched-invocation")

#: `case.arm` is optional (protocol.md/#273); a trial declaring none still
#: needs a row key component, distinct from any real declared value.
UNSPECIFIED_ARM = "unspecified"

#: The report's own `inventory` field (never confused with `SKILL_EVIDENCE_
#: RECONCILIATION`'s unrelated vocabulary of the same shape).
INVENTORY_DECLARED = "declared"
INVENTORY_NOT_DECLARED = "not_declared"


class CoverageRefused(ValueError):
    """The bundle failed its own validation rules, or the report was asked
    for something it structurally cannot answer (e.g. a row count without a
    declared inventory). Never raised for a merely empty population."""


def _refuse(message: str) -> CoverageRefused:
    return CoverageRefused(f"coverage: {message}")


def _canonical_digest(data: object) -> str:
    """The same canonical-JSON + sha256 convention `skillc profile validate`
    already uses for `profile_digest` (`skillc/profile.py`) - reused so a
    report's recorded profile digest is comparable to that command's own
    output, not a second, incompatible convention."""
    import hashlib

    blob = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(blob).hexdigest()


@dataclass(frozen=True)
class DeclaredInventory:
    """The caller-resolved declared-skill selection this report is scoped
    to. Resolving `Profile.select is None` ("full-pack") into a concrete
    skill list needs a live checkout of the subject tree (`profile.py`'s
    own `validate()` materializes one) - out of scope for a tool that reads
    only retained bundles, so callers pass an already-resolved list here,
    never a raw `Profile` object.

    `profile_digest` and `subject_digest` are recorded in the report (not
    merely used to join), because two profiles sharing one subject digest
    but different selections would otherwise produce different inventories
    from the same bundle with nothing in the report showing which one
    produced it (orchestrator review, #272). Reproducibility is a property
    of the (bundle, inventory) pair, never of the bundle alone.
    """

    skills: tuple[str, ...]
    profile_digest: str
    subject_digest: str

    @staticmethod
    def from_profile_raw(skills: Sequence[str], profile_raw: Mapping[str, object], subject_digest: str) -> DeclaredInventory:
        """`profile_raw` is a `Profile.raw`-shaped mapping (or any canonical
        equivalent) - digested with the same convention `validate()` uses,
        never recomputed ad hoc."""
        return DeclaredInventory(
            skills=tuple(sorted(set(skills))),
            profile_digest=_canonical_digest(profile_raw),
            subject_digest=subject_digest,
        )


@dataclass(frozen=True)
class RowKey:
    skill_path: str
    skill_version: str
    client_name: str
    client_version: str
    case_id: str
    arm: str

    def as_tuple(self) -> tuple[str, str, str, str, str, str]:
        return (self.skill_path, self.skill_version, self.client_name, self.client_version, self.case_id, self.arm)


@dataclass(frozen=True)
class CriterionRow:
    id: str
    outcome: str
    shared: bool


@dataclass(frozen=True)
class CoverageRow:
    key: RowKey
    scheduled: int
    evaluable: int
    outcomes: Mapping[str, int]
    coverage_flags: Mapping[str, int]
    reconciliation_counts: Mapping[str, int]
    criteria: tuple[CriterionRow, ...]
    execution_observed: Mapping[str, int]
    read_observed: Mapping[str, int]
    evidence: tuple[str, ...]  # attempt ids backing this row, sorted

    def to_dict(self) -> dict[str, object]:
        return {
            "skill_path": self.key.skill_path,
            "skill_version": self.key.skill_version,
            "client_name": self.key.client_name,
            "client_version": self.key.client_version,
            "case_id": self.key.case_id,
            "arm": self.key.arm,
            "scheduled": self.scheduled,
            "evaluable": self.evaluable,
            "outcomes": dict(self.outcomes),
            "coverage_flags": dict(self.coverage_flags),
            "reconciliation_counts": dict(self.reconciliation_counts),
            "criteria": [{"id": c.id, "outcome": c.outcome, "shared": c.shared} for c in self.criteria],
            "execution_observed": dict(self.execution_observed),
            "read_observed": dict(self.read_observed),
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class CasePairVerdict:
    """One certified `case.arm` pairing's discrimination verdict, with the
    per-arm facts it was computed from kept beside it - never replaced by
    it (orchestrator review, #272)."""

    case_id: str
    case_revision: str
    paired_case_id: str
    paired_case_revision: str
    intact_pass: int
    intact_evaluable: int
    degraded_pass: int
    degraded_evaluable: int
    verdict: str
    p_value: float | None
    reason: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id, "case_revision": self.case_revision,
            "paired_case_id": self.paired_case_id, "paired_case_revision": self.paired_case_revision,
            "intact_pass": self.intact_pass, "intact_evaluable": self.intact_evaluable,
            "degraded_pass": self.degraded_pass, "degraded_evaluable": self.degraded_evaluable,
            "verdict": self.verdict, "p_value": self.p_value, "reason": self.reason,
        }


@dataclass(frozen=True)
class CoverageReport:
    inventory: str
    profile_digest: str | None
    subject_digest: str | None
    declared_skills: tuple[str, ...] | None
    rows: tuple[CoverageRow, ...]
    case_pairs: tuple[CasePairVerdict, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "inventory": self.inventory,
            "profile_digest": self.profile_digest,
            "subject_digest": self.subject_digest,
            "declared_skills": list(self.declared_skills) if self.declared_skills is not None else None,
            "rows": [r.to_dict() for r in sorted(self.rows, key=lambda row: row.key.as_tuple())],
            "case_pairs": [
                p.to_dict() for p in sorted(self.case_pairs, key=lambda p: (p.case_id, p.case_revision))
            ],
        }

    def to_json(self) -> str:
        """Canonical, byte-identical for a given (bundle, inventory) pair
        regardless of input record order - sorted keys, sorted rows, no
        report-generation timestamp anywhere in the body."""
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def _refuse_on_invalid_bundle(bundle: records.Bundle) -> None:
    findings: list[str] = []
    for record in bundle.records:
        findings.extend(f.detail for f in checks.run_record(record))
    findings.extend(f.detail for f in checks.run_bundle(bundle))
    if findings:
        raise _refuse(
            f"bundle fails its own validation rules ({len(findings)} finding(s)); "
            f"first: {findings[0]}"
        )


def _ledger_cells(ledger: records.Record) -> list[tuple[dict[str, object], list[str]]]:
    """One entry per trial: the trial's own identity dict, and its planned
    attempt ids. A trial IS a cell (client, case, arm) - every attempt it
    plans shares that cell."""
    trials = ledger.data.get("trials")
    if not isinstance(trials, list):
        return []
    out: list[tuple[dict[str, object], list[str]]] = []
    for trial in trials:
        if not isinstance(trial, dict):
            continue
        attempts = trial.get("attempts")
        if not isinstance(attempts, list):
            continue
        ids = [
            str(a["attempt_id"]) for a in attempts
            if isinstance(a, dict) and isinstance(a.get("attempt_id"), str)
        ]
        out.append((trial, ids))
    return out


def _attempt_outcome(
    attempt_id: str,
    lifecycles: Mapping[str, records.Record],
    results: Mapping[str, list[records.Record]],
) -> str:
    """One of OUTCOMES, mirroring `attempt_accounting`'s own division of an
    attempt's account: disposition first, then (for a captured attempt)
    whether a real graded result exists yet."""
    lifecycle = lifecycles.get(attempt_id)
    if lifecycle is None:
        return "UNKNOWN"
    disposition = lifecycle.data.get("disposition")
    if disposition == "not-run":
        return "NOT_RUN"
    if disposition == "unavailable":
        return "UNAVAILABLE"
    if disposition == "inconclusive":
        return "UNKNOWN"
    # disposition == "captured"
    graded = [
        r for r in results.get(attempt_id, [])
        if r.data.get("run_state") not in records.DECLARABLE_RUN_STATES
    ]
    if not graded:
        return "UNKNOWN"  # captured, grading still owed
    status = graded[0].data.get("status")
    return status if status in ("PASS", "FAIL") else "UNKNOWN"


def _cell_pass_evaluable(
    attempt_ids: Sequence[str],
    lifecycles: Mapping[str, records.Record],
    results: Mapping[str, list[records.Record]],
) -> tuple[int, int]:
    """(pass count, evaluable count) over a cell's own attempts, reusing
    `_attempt_outcome` so this agrees exactly with each row's own
    `outcomes` - never a second, drifting derivation of the same fact."""
    passes = 0
    evaluable = 0
    for attempt_id in attempt_ids:
        outcome = _attempt_outcome(attempt_id, lifecycles, results)
        if outcome in ("PASS", "FAIL"):
            evaluable += 1
            if outcome == "PASS":
                passes += 1
    return passes, evaluable


def _find_case_pairs(
    cells: Sequence[tuple[dict[str, object], list[str]]],
) -> list[tuple[dict[str, object], list[str], dict[str, object], list[str]]]:
    """Every `(intact trial+ids, degraded trial+ids)` pair declared in this
    bundle. Reciprocity, complementarity and uniqueness are #273's own
    `case-pairing` bundle rule's job, already enforced by refuse-before-
    reporting - this just reads the (already-validated) declaration, it
    does not re-check it."""
    by_case: dict[tuple[str, str], tuple[dict[str, object], list[str]]] = {}
    for trial, ids in cells:
        case = trial.get("case")
        if isinstance(case, dict) and _nonempty_str(case.get("id")) and _nonempty_str(case.get("revision")):
            by_case[(case["id"], case["revision"])] = (trial, ids)

    pairs: list[tuple[dict[str, object], list[str], dict[str, object], list[str]]] = []
    for trial, ids in cells:
        case = trial.get("case")
        if not isinstance(case, dict) or case.get("arm") != "intact":
            continue
        paired_with = case.get("paired_with")
        if not isinstance(paired_with, dict):
            continue
        key = (paired_with.get("id"), paired_with.get("revision"))
        partner = by_case.get(key)  # type: ignore[arg-type]
        if partner is not None:
            pairs.append((trial, ids, partner[0], partner[1]))
    return pairs


def _nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _transcript_missing(attempt_id: str, manifests: Mapping[str, records.Record]) -> bool:
    manifest = manifests.get(attempt_id)
    if manifest is None:
        return True
    observations = manifest.data.get("observations")
    if not isinstance(observations, list):
        return True
    for entry in observations:
        if isinstance(entry, dict) and entry.get("stream") == records.CLIENT_TRANSCRIPT:
            return entry.get("coverage") == "missing"
    return True  # the stream was never declared at all


def assemble_coverage_report(
    bundle: records.Bundle,
    inventory: DeclaredInventory | None = None,
    discrimination_rule: rel.TwoArmRule | None = None,
) -> CoverageReport:
    """The report for one bundle, optionally scoped to a declared inventory.

    Refuses (never silently reports over) a bundle that fails its own
    validation rules, or an `inventory` whose `subject_digest` disagrees
    with any trial's own `subject.digest` in this bundle.

    `discrimination_rule`, when supplied, is applied to every certified
    `case.arm` pairing found in the bundle (module docstring) - omitted
    entirely, `case_pairs` is still populated, each verdict `UNKNOWN`
    ("no predeclared rule"), per `reliability.evaluate_discrimination`'s own
    behavior for a missing rule. Per-arm facts are always present
    regardless of the rule.
    """
    _refuse_on_invalid_bundle(bundle)

    ledgers = bundle.of_kind(records.TRIAL_LEDGER)
    if len(ledgers) != 1:
        raise _refuse(f"bundle holds {len(ledgers)} trial ledgers; exactly one issues its cells")
    ledger = ledgers[0]

    lifecycles = {r.attempt_id: r for r in bundle.of_kind(records.ATTEMPT_LIFECYCLE)}
    manifests = {r.attempt_id: r for r in bundle.of_kind(records.ARTIFACT_MANIFEST)}
    receipts = {r.attempt_id: r for r in bundle.of_kind(records.INSTALLATION_RECEIPT)}
    results: dict[str, list[records.Record]] = {}
    for result in bundle.of_kind(records.VERIFIED_RESULT):
        results.setdefault(result.attempt_id, []).append(result)
    evidence_by_attempt: dict[str, records.Record] = {r.attempt_id: r for r in bundle.of_kind(records.SKILL_EVIDENCE)}

    cells = _ledger_cells(ledger)
    for trial, _ids in cells:
        subject = trial.get("subject")
        subject_digest = subject.get("digest") if isinstance(subject, dict) else None
        if inventory is not None and subject_digest != inventory.subject_digest:
            raise _refuse(
                f"trial {trial.get('trial_id')!r} declares subject digest {subject_digest!r}, "
                f"which disagrees with the supplied inventory's {inventory.subject_digest!r}"
            )

    rows: list[CoverageRow] = []
    if inventory is not None:
        declared_skills = inventory.skills
        for trial, attempt_ids in cells:
            client_raw, case_raw = trial.get("client"), trial.get("case")
            client: Mapping[str, object] = client_raw if isinstance(client_raw, dict) else {}
            case: Mapping[str, object] = case_raw if isinstance(case_raw, dict) else {}
            arm_raw = case.get("arm")
            arm = arm_raw if isinstance(arm_raw, str) else UNSPECIFIED_ARM
            for skill_path in declared_skills:
                rows.append(
                    _build_row(
                        skill_path, attempt_ids, client, case, arm,
                        lifecycles, manifests, receipts, results, evidence_by_attempt,
                    )
                )
        if len(rows) != len(declared_skills) * len(cells):
            raise _refuse(
                f"assembled {len(rows)} row(s), not the expected "
                f"{len(declared_skills)} declared skill(s) * {len(cells)} planned cell(s)"
            )
        row_keys = [r.key.as_tuple() for r in rows]
        if len(set(row_keys)) != len(row_keys):
            # The length check above cannot see THIS: a duplicate entry in
            # `declared_skills` (bypassing `from_profile_raw`'s own dedup)
            # inflates both sides of that product equally - one extra
            # declared skill, one extra row - so it still matches while two
            # rows silently share a key. Caught by uniqueness instead.
            raise _refuse("declared inventory names a skill more than once; row keys would collide")
    else:
        # No declared inventory: rows exist only for skills the bundle
        # itself evidences. NEVER falls back to installation-receipt.
        # installed - that lists every installed file, not just skills
        # under evaluation (orchestrator review, #272).
        for trial, attempt_ids in cells:
            client_raw, case_raw = trial.get("client"), trial.get("case")
            client = client_raw if isinstance(client_raw, dict) else {}
            case = case_raw if isinstance(case_raw, dict) else {}
            arm_raw = case.get("arm")
            arm = arm_raw if isinstance(arm_raw, str) else UNSPECIFIED_ARM
            evidenced_paths: set[str] = set()
            for attempt_id in attempt_ids:
                ev = evidence_by_attempt.get(attempt_id)
                skills = ev.data.get("skills") if ev is not None else None
                for entry in skills if isinstance(skills, list) else []:
                    skill = entry.get("skill") if isinstance(entry, dict) else None
                    path = skill.get("path") if isinstance(skill, dict) else None
                    if isinstance(path, str) and path:
                        evidenced_paths.add(path)
            for skill_path in sorted(evidenced_paths):
                rows.append(
                    _build_row(
                        skill_path, attempt_ids, client, case, arm,
                        lifecycles, manifests, receipts, results, evidence_by_attempt,
                    )
                )

    case_pairs: list[CasePairVerdict] = []
    for intact_trial, intact_ids, degraded_trial, degraded_ids in _find_case_pairs(cells):
        intact_pass, intact_evaluable = _cell_pass_evaluable(intact_ids, lifecycles, results)
        degraded_pass, degraded_evaluable = _cell_pass_evaluable(degraded_ids, lifecycles, results)
        verdict = rel.evaluate_discrimination(
            discrimination_rule, intact_pass, intact_evaluable, degraded_pass, degraded_evaluable,
            certified=True,
        )
        intact_case, degraded_case = intact_trial["case"], degraded_trial["case"]
        assert isinstance(intact_case, dict) and isinstance(degraded_case, dict)
        case_pairs.append(CasePairVerdict(
            case_id=str(intact_case["id"]), case_revision=str(intact_case["revision"]),
            paired_case_id=str(degraded_case["id"]), paired_case_revision=str(degraded_case["revision"]),
            intact_pass=intact_pass, intact_evaluable=intact_evaluable,
            degraded_pass=degraded_pass, degraded_evaluable=degraded_evaluable,
            verdict=verdict.verdict, p_value=verdict.p_value, reason=verdict.reason,
        ))

    return CoverageReport(
        inventory=INVENTORY_DECLARED if inventory is not None else INVENTORY_NOT_DECLARED,
        profile_digest=inventory.profile_digest if inventory is not None else None,
        subject_digest=inventory.subject_digest if inventory is not None else None,
        declared_skills=inventory.skills if inventory is not None else None,
        rows=tuple(rows),
        case_pairs=tuple(case_pairs),
    )


def compute_improvement(
    rule: rel.TwoArmRule | None,
    cpp_pass: int, cpp_evaluable: int,
    baseline_pass: int, baseline_evaluable: int,
) -> rel.TwoArmVerdict:
    """Thin passthrough to `reliability.evaluate_improvement`, for a caller
    with its OWN CPP-vs-baseline (`config.arm`) counts. `config.arm` is not
    a validated field in `skillc/records.py` (module docstring), so this
    module does not discover pairs for it the way `_find_case_pairs` does
    for `case.arm` - the caller supplies the counts directly."""
    return rel.evaluate_improvement(rule, cpp_pass, cpp_evaluable, baseline_pass, baseline_evaluable)


def _build_row(
    skill_path: str,
    attempt_ids: Sequence[str],
    client: Mapping[str, object],
    case: Mapping[str, object],
    arm: str,
    lifecycles: Mapping[str, records.Record],
    manifests: Mapping[str, records.Record],
    receipts: Mapping[str, records.Record],
    results: Mapping[str, list[records.Record]],
    evidence_by_attempt: Mapping[str, records.Record],
) -> CoverageRow:
    outcomes = dict.fromkeys(OUTCOMES, 0)
    coverage_flags = dict.fromkeys(COVERAGE_FLAGS, 0)
    reconciliation_counts = dict.fromkeys(records.SKILL_EVIDENCE_RECONCILIATION, 0)
    execution_observed = dict.fromkeys(records.SKILL_EVIDENCE_CONFIRMATION, 0)
    read_observed = dict.fromkeys(records.SKILL_EVIDENCE_CONFIRMATION, 0)
    criteria: dict[str, CriterionRow] = {}
    versions: set[str] = set()
    evidence_ids: list[str] = []

    for attempt_id in attempt_ids:
        outcome = _attempt_outcome(attempt_id, lifecycles, results)
        outcomes[outcome] += 1
        if _transcript_missing(attempt_id, manifests):
            coverage_flags["missing-transcript"] += 1

        receipt = receipts.get(attempt_id)
        if receipt is not None:
            installed = receipt.data.get("installed")
            for entry in installed if isinstance(installed, list) else []:
                if isinstance(entry, dict) and entry.get("path") == skill_path:
                    digest = entry.get("digest")
                    if isinstance(digest, str) and digest:
                        versions.add(digest)

        ev = evidence_by_attempt.get(attempt_id)
        skills = ev.data.get("skills") if ev is not None else None
        for entry in skills if isinstance(skills, list) else []:
            skill = entry.get("skill") if isinstance(entry, dict) else None
            path = skill.get("path") if isinstance(skill, dict) else None
            if path != skill_path:
                continue
            evidence_ids.append(attempt_id)
            lifecycle_facts = entry.get("lifecycle")
            if isinstance(lifecycle_facts, dict):
                for field_name, bucket in (("execution_observed", execution_observed), ("read_observed", read_observed)):
                    fact = lifecycle_facts.get(field_name)
                    status = fact.get("status") if isinstance(fact, dict) else None
                    if status in bucket:
                        bucket[status] += 1
            external = entry.get("external_evidence")
            if isinstance(external, dict):
                reconciliation = external.get("reconciliation")
                if reconciliation in reconciliation_counts:
                    reconciliation_counts[reconciliation] += 1
                if external.get("present") is True and reconciliation == "unmatched":
                    coverage_flags["unmatched-invocation"] += 1
            owned = entry.get("criteria_owned")
            for c in owned if isinstance(owned, list) else []:
                if not isinstance(c, dict):
                    continue
                c_id = c.get("id")
                if isinstance(c_id, str) and c_id:
                    criteria[c_id] = CriterionRow(id=c_id, outcome=str(c.get("outcome")), shared=bool(c.get("shared")))

    # Every attempt under one trial shares that trial's installation plan, so
    # a validated bundle's receipts agree on one digest per skill path here -
    # a cross-TRIAL version difference (the "stale version" shape) already
    # produces separate rows for free, one per cell, without this function
    # needing to split anything itself.
    skill_version = min(versions) if versions else "UNKNOWN"
    scheduled = len(attempt_ids)
    evaluable = outcomes["PASS"] + outcomes["FAIL"]
    key = RowKey(
        skill_path=skill_path,
        skill_version=skill_version,
        client_name=str(client.get("name", "")),
        client_version=str(client.get("version", "")),
        case_id=str(case.get("id", "")),
        arm=arm,
    )
    return CoverageRow(
        key=key,
        scheduled=scheduled,
        evaluable=evaluable,
        outcomes=outcomes,
        coverage_flags=coverage_flags,
        reconciliation_counts=reconciliation_counts,
        criteria=tuple(sorted(criteria.values(), key=lambda c: c.id)),
        execution_observed=execution_observed,
        read_observed=read_observed,
        evidence=tuple(sorted(set(evidence_ids))),
    )
