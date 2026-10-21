"""Calibrate before comparing (issue #204): the symmetric primary endpoint and
the two-arm calibration declaration that precede the #203 effectiveness study.

THE TRAP THIS MODULE EXISTS TO CLOSE. An agent-trial attempt carries two
statuses, and only one of them is fair to a baseline arm:

  - `record["graded"]["status"]` - the TASK grade: the task grader's own
    criteria and nothing else (`agent_trial.run_one_attempt`).
  - `record["graded"]["result_status"]` - the stored `verified-result`'s
    status, which adds the verifier's own mandatory `installation-ready`
    criterion (`verify.READINESS_CRITERION`).

An arm that installs nothing stays on the `AGENT_OBSERVATION_READINESS`
stand-in, whose `installation-ready` is always UNKNOWN (#139, ADR 0005's
"yes, narrow B1"), so its `result_status` can never be PASS. An arm that
installs a codex collection through `collection_conformance` writes a real
installation receipt and CAN reach PASS. Comparing `result_status` rates
between a CPP arm and a baseline arm therefore manufactures a CPP advantage
out of grading plumbing.

`primary_endpoint` is the comparison's endpoint: the task grader's criteria
(for `evals/level3/slugkit-pipeline`, the task AND its pipeline checks),
derived with `records.derive_status`, never `installation-ready`. Readiness is
reported beside it by `readiness_beside`, never folded in and never a hidden
precondition only one arm can meet. This is issue #204's "Option B"; a
baseline readiness receipt ("Option A") would need `records.
installation_receipt` to accept an empty `installed` list, which it refuses
by design, and would only ever exist for codex.

THE DECLARATION. `load_declaration` validates a calibration run manifest
(`evals/calibration-204/run-manifest.json`) BEFORE any attempt exists:
two or three arms that differ only in their treatment (every other identity
lives once, under `shared`), 1-1000 attempts per arm (#323: a sanity rail,
not a design-sizing constraint - see `MIN_ATTEMPTS_PER_ARM`), and an arm
order derived from a recorded seed rather than chosen by hand. A third arm
(#231, the #203
B/N/P design) installs the SAME subject as the other treated arm and differs
from it only by an `instruction` naming `named_skills` to read first: it
separates a skill's value from its uptake, and can never be an ablation. A declaration is not an
authorization: `require_approved` refuses one whose `approval` is not
recorded, or whose identities still say `UNKNOWN` (ADR 0005: no live run
without recorded, approved arms, identities, schedule and caps).

Nothing here runs an agent. Task definitions, graders and mutation contracts
stay subject-independent: nothing in this module names or branches on a
particular subject.

Stdlib only (AGENTS.md), plus this repository's own modules.
"""

from __future__ import annotations

import json
import math
import random
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import degrade, profile, records, trial, verify
from . import materialize as m

#: The criteria the primary endpoint never reads, whatever a record carries.
PRIMARY_ENDPOINT_EXCLUDES = frozenset({verify.READINESS_CRITERION})

#: The status of an attempt no grade exists for. Not a protocol status: the
#: attempt never reached the endpoint, and it is reported, never dropped.
NOT_GRADED = "NOT_GRADED"

BASELINE_ARM = "baseline"
#: #323: the fixed 3-8 range this module shipped with (#204) refused any
#: declaration that needed more repeats than that to reach significance.
#: evals/calibration-287/power_cost_table.py showed a concrete case: even at
#: the best observable outcome (the better arm passing every attempt), a
#: one-sided Fisher's exact test at alpha=0.05 needs n>=10 per arm to reach
#: p<0.05 at all. 1 is the only real floor (a single attempt is still a
#: result, just an uninformative one - `require_approved`'s identity/grader
#: checks catch a careless declaration long before power does); the upper
#: bound is a sanity rail against a typo'd exponent (a declared six-figure
#: attempts_per_arm was never a deliberate study design), not a design-
#: sizing constraint - that question belongs to the declaration's own power
#: justification and to ADR 0005's cost gate, not to this schema.
MIN_ATTEMPTS_PER_ARM, MAX_ATTEMPTS_PER_ARM = 1, 1_000
UNKNOWN = "UNKNOWN"

#: protocol.md 10.1: the three lanes a declaration may measure. Absent (every
#: declaration before #274) means `matched-outcome` - #203/#231's existing
#: baseline-vs-treatment-vs-provided design, never renamed, just now
#: nameable. This module only adds validation for `expanded-instruction`;
#: `explicit-contract` is #273's own statistics, not implemented here.
LANES = ("explicit-contract", "matched-outcome", "expanded-instruction")
DEFAULT_LANE = "matched-outcome"
EXPANDED_INSTRUCTION_LANE = "expanded-instruction"

#: The only keys an arm may carry. Anything else - a model, an effort, a
#: timeout - would be a second difference between the arms; it belongs under
#: `shared`, once, for both. `inventory` is #274's addition for the
#: expanded-instruction lane; harmless (and refused if present) on every
#: other lane's arms. (`obligation` was considered and dropped: protocol.md
#: 10.2's obligation record - source/class/scope/evidence/rule/applies_when
#: - is #273's grading-layer concern; #274's "equal obligations" acceptance
#: item is already satisfied structurally by the existing same-subject/
#: same-task/same-shared-identities checks, with nothing left for a flat
#: arm-level field to add.)
ARM_KEYS = frozenset({"name", "subject", "treatment", "instruction", "named_skills", "inventory"})

#: The keys only a provided-skill arm carries, always together (#231).
PROVIDED_KEYS = frozenset({"instruction", "named_skills"})

#: #274, protocol.md 10.4: the expanded-instruction lane's two treated arms,
#: both installing the profile at `inventory` (one shared, validated
#: `skillc profile validate` output, pinned by path and digest). S keeps the
#: existing PROVIDED_KEYS shape (a short instruction naming the skill); E
#: carries `instruction` alone - the inlined obligation text - which
#: `matched-outcome`'s "natural arm stays unnudged" rule would otherwise
#: refuse (#274 acceptance item 3: unnudged unless the lane says otherwise).
EXPANDED_INSTRUCTION_KEYS = frozenset({"inventory"})

#: What both arms must share, by construction (issue #204's Scope).
SHARED_KEYS = frozenset({
    "client", "model", "reasoning_effort", "tools", "permissions", "public_requirements",
    "image", "per_attempt_seconds", "total_seconds",
})

#: skillc#287: the discrimination test's own shape (intact vs degraded).
#: Never `parse_declaration`'s business - neither arm installs nothing, so
#: neither can be the literal `BASELINE_ARM`, and a 3-arm declaration's
#: "treated arms share an identical subject" rule also refuses it (a
#: degraded arm's revision is never identical to intact's, by construction
#: - see `_expected_degraded_revision`). Orchestrator ruling on #287
#: (2026-10-06): add this kind rather than writing a declaration against a
#: shape `parse_declaration` cannot load.
DISCRIMINATION_KIND = "discrimination-declaration"
DISCRIMINATION_ARMS = ("intact", "degraded")

#: The keys a degraded arm's structured mutation records (#287): the single
#: file edit this discrimination tests, the evidence that no other
#: installed skill or helper still carries what it removes, and the
#: resulting file's own content identity. `skillc/degrade.py`'s own
#: `Mutation`/`FileEdit` shape, narrowed to exactly one file edit - a
#: discrimination declaration states ONE mutation, never a general degrade.
#: `mutated_digest` exists because `degrade._degraded_revision`'s label
#: encodes the LOCATION COUNT and the base revision, never the edit's own
#: bytes (verified directly: two edits of the same file with different
#: content produce an identical label) - so the label alone cannot tell two
#: different removals of the same file apart. `mutated_digest` is the
#: sha256 of the degraded file's bytes (the intact file at the pinned
#: revision with exactly `removed_text` removed); this module checks only
#: its FORMAT. Verifying it against the real intact file, and that
#: `removed_text` occurs in it exactly once, are run-time preconditions of
#: every live attempt, enforced by `require_degraded_mutation` (#287 P2)
#: against the acquired intact bytes before any attempt is planned.
MUTATION_KEYS = frozenset({"skill", "path", "removed_text", "diagnose_evidence", "mutated_digest"})

#: `sha256:` + 64 lowercase hex characters - `materialize.tree_digest`'s own
#: format, reused here for `mutation.mutated_digest` rather than inventing
#: a second digest convention.
_SHA256_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")


class DeclarationRefused(ValueError):
    """The calibration declaration is not one a run could honestly follow."""


@dataclass(frozen=True)
class OutcomeEndpoint:
    """An explicitly approved common task outcome, separate from process evidence."""

    criteria: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {"version": 1, "name": "common-task-outcome", "criteria": list(self.criteria)}


def _outcome_endpoint(data: Mapping[str, object]) -> OutcomeEndpoint | None:
    present = {"outcome_endpoint", "task_content"} & data.keys()
    if not present:
        return None
    if len(present) != 2:
        raise _refuse("outcome_endpoint and task_content must occur together")
    raw, content = data["outcome_endpoint"], data["task_content"]
    if not isinstance(raw, dict) or set(raw) != {"version", "name", "criteria"} \
            or type(raw.get("version")) is not int or raw["version"] != 1 \
            or raw.get("name") != "common-task-outcome":
        raise _refuse("outcome_endpoint must name the closed common-task-outcome version 1 schema")
    criteria = raw["criteria"]
    if not isinstance(criteria, list) or not criteria \
            or not all(isinstance(c, str) and c.strip() == c and c for c in criteria) \
            or len(set(criteria)) != len(criteria) or PRIMARY_ENDPOINT_EXCLUDES.intersection(criteria):
        raise _refuse("outcome_endpoint.criteria must be distinct nonempty task criterion names")
    bound = ("goal_digest", "grader_digest", "fixture_digest")
    # #508: a task that declares a project gate binds its declaration too;
    # every other task's task_content is exactly as before.
    gated = isinstance(content, dict) and "project_gate_digest" in content
    if not isinstance(content, dict) \
            or set(content) != {"version", *bound, *(("project_gate_digest",) if gated else ())} \
            or type(content.get("version")) is not int or content["version"] != 1 \
            or not all(isinstance(content[k], str) and _SHA256_DIGEST_RE.fullmatch(content[k])
                       for k in (*bound, *(("project_gate_digest",) if gated else ()))):
        raise _refuse("task_content must bind goal, grader and fixture digests (and a declared project gate's) "
                      "under version 1")
    arms = data.get("arms")
    if data.get("kind") != "calibration-declaration" or data.get("lane", DEFAULT_LANE) != DEFAULT_LANE \
            or not isinstance(arms, list) or len(arms) != 2 \
            or any(not isinstance(a, dict) or "instruction" in a for a in arms):
        raise _refuse("common-task-outcome requires a two-arm matched-outcome declaration without instructions")
    return OutcomeEndpoint(tuple(criteria))


def outcome_endpoint(declaration: CalibrationDeclaration) -> OutcomeEndpoint | None:
    return _outcome_endpoint(declaration.data)


@dataclass(frozen=True)
class DiscriminationEndpoint(OutcomeEndpoint):
    """#287 option 1: the OBLIGATION a discrimination contrast measures, scored
    on its own criterion rather than the task grader's composite. Without it,
    an honest report whose fix failed is a composite FAIL (counted as not
    honest), and an unknown honesty beside a failed task criterion is an
    EVALUABLE FAIL - neither measures what the degraded arm removes.

    A field of its own, never `outcome_endpoint`: that is the improvement
    study's common-task subset, which a discrimination contrast must not
    inherit (#287's rule). Absent, a discrimination report is exactly what it
    was."""

    def to_json(self) -> dict[str, object]:
        return {"version": 1, "name": "discrimination-obligation", "criteria": list(self.criteria)}


def _discrimination_endpoint(data: Mapping[str, object]) -> DiscriminationEndpoint | None:
    if "discrimination_endpoint" not in data:
        return None
    if data.get("kind") != DISCRIMINATION_KIND:
        raise _refuse("discrimination_endpoint belongs to a discrimination declaration only")
    raw = data["discrimination_endpoint"]
    if not isinstance(raw, dict) or set(raw) != {"version", "name", "criteria"} \
            or type(raw.get("version")) is not int or raw["version"] != 1 \
            or raw.get("name") != "discrimination-obligation":
        raise _refuse("discrimination_endpoint must name the closed discrimination-obligation version 1 schema")
    criteria = raw["criteria"]
    if not isinstance(criteria, list) or not criteria \
            or not all(isinstance(c, str) and c.strip() == c and c for c in criteria) \
            or len(set(criteria)) != len(criteria) or PRIMARY_ENDPOINT_EXCLUDES.intersection(criteria):
        raise _refuse("discrimination_endpoint.criteria must be distinct nonempty task criterion names")
    return DiscriminationEndpoint(tuple(criteria))


def declaration_digest(data: Mapping[str, object]) -> str:
    """Exact declaration identity, excluding only the self-referential approval."""
    return trial.sha256_bytes(trial.canonical({k: v for k, v in data.items() if k != "approval"}))


#: #287 P2 (orchestrator ruling D-P2a): an approval binds the WHOLE
#: declaration - `approval.declaration_digest` must equal
#: `declaration_digest(data)` for every kind, so any field changed after
#: approval (client, model, effort, image, caps, seed, ...) is refused.
#: These four committed declarations were approved before that rule and carry
#: no declaration_digest; each is pinned here by its OWN canonical digest so
#: historical approved evidence keeps its meaning. The pin cannot be claimed
#: by any other declaration: editing one of these four changes its digest, so
#: it falls out of this set and must then carry a declaration_digest.
LEGACY_APPROVED_DECLARATION_DIGESTS: Mapping[str, str] = {
    "sha256:0e95ebda72858a3f5fb2c7874793182a01ffb665be65605e7e6db61d43804f4d": "evals/calibration-203/run-manifest.json",
    "sha256:e7234cc190c0a814528327ae8aba035805a8d5ffe5bd094b53089166118834a2": "evals/calibration-203-c3/run-manifest.json",
    "sha256:48319cf9b2d8020347ec2b9f6919cbf9ad5fbee80da41015db7f4f2f1acbf72f": "evals/calibration-203-low/run-manifest.json",
    "sha256:1636bc7aaf5151253b845f41077b2da119732b755d70b3fd75f5104a7578c34d": "evals/calibration-204/run-manifest.json",
}


def _require_whole_declaration_approval(data: Mapping[str, object], approval: Mapping[str, object]) -> None:
    """The approval must name this exact declaration (D-P2a), unless the
    declaration is one of the pinned pre-rule approvals above."""
    digest = declaration_digest(data)
    if digest in LEGACY_APPROVED_DECLARATION_DIGESTS:
        return
    if approval.get("declaration_digest") != digest:
        raise _refuse(f"approval.declaration_digest {approval.get('declaration_digest')!r} does not bind this "
                      f"exact declaration ({digest}); any field changed after approval needs its own approval")


def require_outcome_approval(declaration: CalibrationDeclaration) -> None:
    """Pure check, also usable when replaying the immutable launch declaration."""
    if outcome_endpoint(declaration) is None:
        # Removing outcome fields after approval changes the declaration's
        # digest, so `_require_whole_declaration_approval` (D-P2a, run by every
        # `require_approved*`) refuses it; a declaration_digest on a
        # non-outcome approval is now the normal case, not a removal signal.
        return
    approval = _require_schedule_approval(declaration.approval, declaration.attempts_per_arm)
    if approval.get("declaration_digest") != declaration_digest(declaration.data):
        raise _refuse("approval.declaration_digest does not bind this exact outcome declaration")


def primary_endpoint(
    record: Mapping[str, object], *, endpoint: OutcomeEndpoint | None = None,
) -> dict[str, object]:
    """The primary endpoint for one attempt: the task grader's own criteria
    (task + pipeline checks), status derived by `records.derive_status`.

    `record` is `agent_trial.run_one_attempt`'s returned record. Reads
    `record["graded"]["criteria"]` and NEVER `result_status`. A criterion
    named `installation-ready` is excluded even if a record carries one
    (a hand-built or future record), and the exclusion is stated in the
    result. An attempt with no grade is `NOT_GRADED`, with the reason the
    record gives, never a silent absence or a FAIL."""
    graded = record.get("graded")
    if not isinstance(graded, dict):
        reason = record.get("grading_blocked_reason") or f"disposition {record.get('disposition')!r}"
        return {"status": NOT_GRADED, "criteria": [], "excluded": [], "reason": str(reason)}
    raw = graded.get("criteria")
    if endpoint is not None:
        return _selected_endpoint(raw, endpoint)
    criteria = [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []
    kept = [c for c in criteria if c.get("id") not in PRIMARY_ENDPOINT_EXCLUDES]
    excluded = sorted(str(c.get("id")) for c in criteria if c.get("id") in PRIMARY_ENDPOINT_EXCLUDES)
    status = records.derive_status(records.Record(path=Path("<primary-endpoint>"), data={"criteria": kept}))
    return {
        "status": status,
        "criteria": [{"id": c.get("id"), "mandatory": c.get("mandatory"), "outcome": c.get("outcome")}
                     for c in kept],
        "excluded": excluded,
        "reason": None,
    }


def _selected_endpoint(raw: object, endpoint: OutcomeEndpoint) -> dict[str, object]:
    bad: dict[str, object] = {"status": "INCONCLUSIVE", "criteria": [], "excluded": [],
                             "reason": "selected endpoint requires unique, well-formed mandatory criterion rows"}
    if not isinstance(raw, list) or not raw:
        return bad
    by_id: dict[str, dict[str, object]] = {}
    for row in raw:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] \
                or row["id"] in by_id or type(row.get("mandatory")) is not bool \
                or row.get("outcome") not in records.CRITERION_OUTCOMES:
            return bad
        by_id[row["id"]] = row
    if any(cid not in by_id or by_id[cid]["mandatory"] is not True for cid in endpoint.criteria):
        return bad
    kept = [by_id[cid] for cid in endpoint.criteria]
    for row in kept:
        if row["outcome"] in ("SATISFIED", "VIOLATED") and not records._str_list(row.get("evidence")):
            return {**bad, "reason": f"selected criterion {row['id']!r} has no valid evidence references"}
        if row["outcome"] == UNKNOWN and not records._nonempty_str(row.get("missing")):
            return {**bad, "reason": f"selected criterion {row['id']!r} does not name its missing evidence"}
    status = records.derive_status(records.Record(Path("<common-task-outcome>"), {"criteria": kept}))
    return {"status": status,
            "criteria": [{"id": c["id"], "mandatory": c["mandatory"], "outcome": c["outcome"]} for c in kept],
            "excluded": sorted(set(by_id) - set(endpoint.criteria)), "reason": None}


def readiness_beside(verified_result: Mapping[str, object] | None) -> dict[str, object]:
    """`installation-ready`, reported beside the primary endpoint, from the
    attempt's stored `verified-result` (`result-<id>.json`): its outcome, the
    readiness source the verifier used, and the result's own status - so a
    reader sees WHY the verified status differs from the primary endpoint
    for an arm on the stand-in. `None`/no criterion is `UNKNOWN`, never
    SATISFIED."""
    if not isinstance(verified_result, Mapping):
        return {"installation_ready": UNKNOWN, "readiness_source": UNKNOWN, "verified_status": UNKNOWN,
                "reason": "no verified result"}
    criteria = verified_result.get("criteria")
    ready = next((c for c in criteria if isinstance(c, dict) and c.get("id") == verify.READINESS_CRITERION),
                 None) if isinstance(criteria, list) else None
    verification = verified_result.get("verification")
    source = verification.get("readiness_source") if isinstance(verification, dict) else None
    return {
        "installation_ready": ready.get("outcome", UNKNOWN) if ready else UNKNOWN,
        "readiness_source": source or UNKNOWN,
        "verified_status": verified_result.get("status", UNKNOWN),
        "reason": None if ready else f"the verified result carries no {verify.READINESS_CRITERION} criterion",
    }


def derive_arm_order(seed: int, arms: Sequence[str], attempts_per_arm: int) -> list[str]:
    """The randomized arm order a seed produces: each arm `attempts_per_arm`
    times, shuffled by `random.Random(seed)`. Recorded in the declaration and
    re-derived by `load_declaration`, so the order was not picked by hand
    after the fact."""
    order = [arm for arm in arms for _ in range(attempts_per_arm)]
    random.Random(seed).shuffle(order)
    return order


@dataclass(frozen=True)
class CalibrationDeclaration:
    arms: tuple[str, ...]
    attempts_per_arm: int
    arm_order: tuple[str, ...]
    seed: int
    shared: Mapping[str, object]
    task_path: str
    grader_id: str
    grader_revision: str
    retain_transcripts: bool
    approval: Mapping[str, object] | None
    data: Mapping[str, object]
    lane: str = DEFAULT_LANE
    task_fixture: str = "fixture"
    #: #287 P3 (C2): `tolerance.non_evaluable_per_arm`, REQUIRED for a
    #: declaration with an outcome endpoint (its report applies it), and `None`
    #: for a legacy declaration that declares none.
    tolerance_non_evaluable_per_arm: int | None = None


def _refuse(message: str) -> DeclarationRefused:
    return DeclarationRefused(f"calibration declaration: {message}")


def _positive_number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value) or value <= 0:
        raise _refuse(f"{what} must be a positive, finite number of seconds, not {value!r}")
    return float(value)


def _validated_subject_profile(subject: Mapping[str, object], where: str) -> str | None:
    """skillc#334: a treated arm's subject may OPT IN to having a
    validated profile's dependency closure installed, by naming it here -
    a repo-relative path to its `profile.json`, e.g.
    'evals/subjects/cpp-codex-flow-check-ea6dbfa'. Absent (every
    declaration before #334) means "install the selected skill files
    only" - today's behavior, never inferred (orchestrator ruling: a
    silent `profile.validate` attempt where `Refused`
    means "no profile" would turn a real profile defect into "no
    closure", #334's own bug coming back). Shape only here - no file is
    read; the approval binding (`_require_profile_approval`) and the
    live re-validation both happen later, where file reads are already
    this module's convention (`_require_grader_matches`)."""
    if "profile" not in subject:
        return None
    value = subject.get("profile")
    if not isinstance(value, str) or not value.strip():
        raise _refuse(f"{where}.profile must be a non-empty string naming a profile.json path")
    return value


@dataclass(frozen=True)
class _ScheduleFields:
    """The parsed tail every declaration kind shares, once its own arms are
    validated - see `_parse_schedule_and_identities`."""
    shared: dict[str, object]
    attempts_per_arm: int
    seed: int
    sequence: tuple[str, ...]
    task_path: str
    grader_id: str
    grader_revision: str
    task_fixture: str
    approval: Mapping[str, object] | None


def _parse_schedule_and_identities(data: Mapping[str, object], names: Sequence[str]) -> _ScheduleFields:
    """The tail every declaration kind shares once its own arms are parsed:
    the shared identities block, `attempts_per_arm`, the seed-derived arm
    order (checked against `names`, in the order the caller passes - a
    calibration declaration's own declared order; a discrimination
    declaration's fixed `DISCRIMINATION_ARMS` order), the task pointer,
    `retain_transcripts` and the approval shape.

    Pulled out of `parse_declaration` (#287) so `parse_discrimination_
    declaration` reuses it rather than copying it. `parse_declaration`'s own
    behavior and messages for `kind == 'calibration-declaration'` are
    unchanged by this extraction - every check and every refusal string
    moved here verbatim."""
    shared = data.get("shared")
    if not isinstance(shared, dict):
        raise _refuse("no 'shared' block: the identities both arms run under")
    missing = SHARED_KEYS - set(shared)
    if missing:
        raise _refuse(f"'shared' is missing {sorted(missing)}")
    per_attempt = _positive_number(shared["per_attempt_seconds"], "shared.per_attempt_seconds")
    total = _positive_number(shared["total_seconds"], "shared.total_seconds")

    attempts = data.get("attempts_per_arm")
    if isinstance(attempts, bool) or not isinstance(attempts, int) \
            or not MIN_ATTEMPTS_PER_ARM <= attempts <= MAX_ATTEMPTS_PER_ARM:
        raise _refuse(f"attempts_per_arm must be {MIN_ATTEMPTS_PER_ARM}-{MAX_ATTEMPTS_PER_ARM}, not {attempts!r}")
    if total < per_attempt * attempts * len(names):
        raise _refuse(f"shared.total_seconds {total:g} cannot cover {attempts * len(names)} attempts of "
                      f"{per_attempt:g}s; a total cap that cuts the schedule short is not the declared schedule")

    order = data.get("arm_order")
    if not isinstance(order, dict):
        raise _refuse("no arm_order: the seed and the sequence it produced are recorded before any attempt")
    seed, sequence = order.get("seed"), order.get("sequence")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise _refuse("arm_order.seed must be an integer")
    if not isinstance(sequence, list) or not all(isinstance(s, str) for s in sequence):
        raise _refuse("arm_order.sequence must be a list of arm names")
    expected = derive_arm_order(seed, names, attempts)
    if sequence != expected:
        raise _refuse(f"arm_order.sequence is not what seed {seed} derives ({expected}); "
                      "an order chosen by hand is not a randomized one")

    task = data.get("task")
    if not isinstance(task, dict) or not all(isinstance(task.get(k), str) and task.get(k)
                                             for k in ("path", "grader_id", "grader_revision")):
        raise _refuse("task must name path, grader_id and grader_revision")
    #: Optional (#287): which subdirectory under task.path a live attempt is
    #: actually graded against. Defaults to "fixture" - every declaration
    #: written before this field existed names no "fixture" key, so it
    #: parses to the identical tree it always ran, unchanged. gate-stops-
    #: early's discrimination case is the first to need a different one
    #: (discrimination/fixture): that task's own top-level fixture/ never
    #: exercises the skipped-gate obligation at all (its Makefile declares
    #: every gate), so running the default tree would make the study #150
    #: by construction - found and fixed before any attempt, not after.
    fixture = task.get("fixture", "fixture")
    if not isinstance(fixture, str) or not fixture.strip():
        raise _refuse("task.fixture must be a non-empty string naming a subdirectory under task.path")
    if m._escapes(fixture):
        raise _refuse(f"task.fixture {fixture!r} must be a relative subdirectory under task.path, "
                      "never absolute and never climbing out of it")
    if data.get("retain_transcripts") is not True:
        raise _refuse("retain_transcripts must be true: report question 4 is answered from transcripts (#202)")
    approval = data.get("approval")
    if approval is not None and not isinstance(approval, dict):
        raise _refuse("approval is null (not yet approved) or an object recording who approved and when")

    return _ScheduleFields(
        shared=dict(shared), attempts_per_arm=attempts, seed=seed, sequence=tuple(sequence),
        task_path=str(task["path"]), grader_id=str(task["grader_id"]), grader_revision=str(task["grader_revision"]),
        task_fixture=fixture, approval=approval,
    )


def parse_declaration(data: Mapping[str, object]) -> CalibrationDeclaration:
    """Validate a declaration's shape. See the module docstring for what it
    requires and why; every refusal names the field. Shape only - no file is
    read here, `lane` included: the expanded-instruction lane's inventory
    content (treatment_question, helper parity, body digests) is checked by
    `validate_expanded_instruction_lane`, which needs a repository root this
    function does not take, consistent with `require_approved` doing the
    grader file-read rather than this function."""
    if data.get("kind") != "calibration-declaration":
        raise _refuse(f"kind is {data.get('kind')!r}, not 'calibration-declaration'")
    _outcome_endpoint(data)
    _discrimination_endpoint(data)  # refused on this kind
    lane = data.get("lane", DEFAULT_LANE)
    if lane not in LANES:
        raise _refuse(f"lane must be one of {LANES}, not {lane!r}")
    arms_raw = data.get("arms")
    if not isinstance(arms_raw, list) or len(arms_raw) not in (2, 3) \
            or not all(isinstance(a, dict) for a in arms_raw):
        raise _refuse("two or three arms are declared (baseline, treatment, and optionally a provided-skill "
                      "arm); an ablation belongs to #203, not to calibration")
    names = []
    for arm in arms_raw:
        extra = set(arm) - ARM_KEYS
        if extra:
            raise _refuse(f"arm {arm.get('name')!r} carries {sorted(extra)}; arms may differ only in "
                          f"{sorted(ARM_KEYS)} - everything else is declared once under 'shared'")
        name = arm.get("name")
        if not isinstance(name, str) or not name:
            raise _refuse("every arm needs a name")
        names.append(name)
    if len(set(names)) != len(names) or names.count(BASELINE_ARM) != 1:
        raise _refuse(f"arms must be distinct names, exactly one of them {BASELINE_ARM!r}; got {names}")
    baseline = next(a for a in arms_raw if a["name"] == BASELINE_ARM)
    treated = [a for a in arms_raw if a["name"] != BASELINE_ARM]
    if baseline.get("subject") is not None:
        raise _refuse("the baseline arm installs nothing: its subject is null")
    if PROVIDED_KEYS & set(baseline):
        raise _refuse("the baseline arm installs nothing, so it can name no skill to read")
    if "inventory" in baseline:
        raise _refuse("the baseline arm installs nothing, so it has no inventory to declare")
    expanded = lane == EXPANDED_INSTRUCTION_LANE
    for arm in treated:
        if not isinstance(arm.get("subject"), dict):
            raise _refuse(f"arm {arm['name']!r} names no subject to install")
        _validated_subject_profile(arm["subject"], f"arm {arm['name']!r}.subject")
        provided = PROVIDED_KEYS & set(arm)
        # The expanded-instruction lane's E arm carries `instruction` alone
        # (the inlined obligation text, no skill to name) - every other
        # lane refuses that combination outright (#274 acceptance item 3:
        # a natural arm stays unnudged unless the lane says otherwise).
        is_prose_arm = expanded and provided == {"instruction"}
        if provided and provided != PROVIDED_KEYS and not is_prose_arm:
            raise _refuse(f"arm {arm['name']!r} carries {sorted(provided)} alone; an instruction and the "
                          "named_skills it names are declared together")
        # codex review: an E arm with NEITHER instruction nor named_skills
        # (provided == set()) fell through both branches above - `provided`
        # is falsy, so neither raised - and parse_declaration accepted it,
        # deferring the failure to a bare KeyError inside
        # validate_expanded_instruction_lane instead of a clean refusal here.
        if expanded and not provided and not is_prose_arm:
            raise _refuse(f"arm {arm['name']!r}: the expanded-instruction lane's E arm must carry "
                          "'instruction' alone (the inlined text) - it carries neither instruction nor "
                          "named_skills")
        if expanded:
            inventory = arm.get("inventory")
            if not isinstance(inventory, str) or not inventory.strip():
                raise _refuse(f"arm {arm['name']!r}: the expanded-instruction lane requires a non-empty "
                              "'inventory' path on every treated arm (protocol.md 10.4)")
        elif "inventory" in arm:
            raise _refuse(f"arm {arm['name']!r} carries 'inventory'; that belongs to the "
                          "expanded-instruction lane only")
        if is_prose_arm:
            if not isinstance(arm["instruction"], str) or not arm["instruction"].strip():
                raise _refuse(f"arm {arm['name']!r}: instruction must be non-empty text")
        elif provided:
            skills = arm["named_skills"]
            if not isinstance(arm["instruction"], str) or not arm["instruction"].strip():
                raise _refuse(f"arm {arm['name']!r}: instruction must be non-empty text")
            if not isinstance(skills, list) or not skills \
                    or not all(isinstance(k, str) and k.strip() for k in skills) or len(set(skills)) != len(skills):
                raise _refuse(f"arm {arm['name']!r}: named_skills must be a non-empty list of distinct names")
            if expanded and len(skills) != 1:
                raise _refuse(f"arm {arm['name']!r}: the expanded-instruction lane names exactly one skill "
                              f"(the one E's instruction must match byte-for-byte), not {skills}")
            # A whole name, never a substring: `flow-auto` is not named by
            # `flow-auto-extra` (counter-model review).
            missing_names = [k for k in skills
                             if not re.search(r"(?<![\w-])" + re.escape(k) + r"(?![\w-])", arm["instruction"])]
            if missing_names:
                raise _refuse(f"arm {arm['name']!r}: the instruction does not name {missing_names}")
    if len(treated) == 2:
        if treated[0]["subject"] != treated[1]["subject"]:
            raise _refuse("the two treated arms install different subjects; a third arm may differ only by "
                          "its instruction, never by what is installed (an ablation belongs to #203)")
        if expanded:
            if sum(1 for a in treated if PROVIDED_KEYS <= set(a)) != 1:
                raise _refuse("of the two expanded-instruction arms, exactly one (S) carries an instruction "
                              "and named_skills; the other (E) carries instruction alone")
            if treated[0].get("inventory") != treated[1].get("inventory"):
                raise _refuse("the expanded-instruction lane's two treated arms must reference the SAME "
                              "inventory - helper parity is proven once, for the pair, not twice")
        elif sum(1 for a in treated if PROVIDED_KEYS <= set(a)) != 1:
            raise _refuse("of the two treated arms, exactly one carries an instruction and named_skills; "
                          "otherwise the arms do not differ, or differ in two ways")
    elif expanded:
        raise _refuse("the expanded-instruction lane needs both treated arms (S and E) declared; "
                      "one alone cannot be the contrast protocol.md 10.1 names")
    elif PROVIDED_KEYS & set(treated[0]):
        raise _refuse("a provided-skill arm needs a natural arm beside it, installing the same subject "
                      "without the instruction; alone it confounds value with the instruction")

    fields = _parse_schedule_and_identities(data, names)
    tolerance = _parse_tolerance(data, required=_outcome_endpoint(data) is not None)
    if "run_store" in data:
        _validate_run_store(data.get("run_store"))
    return CalibrationDeclaration(
        arms=tuple(names), attempts_per_arm=fields.attempts_per_arm, arm_order=fields.sequence, seed=fields.seed,
        shared=fields.shared, task_path=fields.task_path, grader_id=fields.grader_id,
        grader_revision=fields.grader_revision, retain_transcripts=True, approval=fields.approval,
        data=dict(data), lane=str(lane), task_fixture=fields.task_fixture,
        tolerance_non_evaluable_per_arm=tolerance,
    )


def _parse_tolerance(data: Mapping[str, object], *, required: bool) -> int | None:
    """`tolerance.non_evaluable_per_arm`: a positive integer fixed before any
    attempt runs. Required where the report applies it (#287 P3, C2)."""
    tolerance = data.get("tolerance")
    value = tolerance.get("non_evaluable_per_arm") if isinstance(tolerance, dict) else None
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _refuse("tolerance.non_evaluable_per_arm must be a positive integer, fixed before any attempt runs")
    return value


#: #287 P3 (C1): words that mark a drafted, not recorded, value. Refused at
#: approval anywhere under `shared` or `arms`, exactly as `UNKNOWN` is: a
#: placeholder is not an identity.
PLACEHOLDER_MARKERS = ("PENDING", "PROPOSED", "UNKNOWN")
_PLACEHOLDER = re.compile(r"\b(?:" + "|".join(PLACEHOLDER_MARKERS) + r")\b")
#: The declaration's IDENTITY: what a run is launched with and bound to. A
#: placeholder token anywhere in one of these leaves is refused (C1).
IDENTITY_ROOTS = ("shared", "arms", "task", "task_content", "run_store", "attempts_per_arm", "tolerance",
                  "arm_order", "skill_pins", "outcome_endpoint")
#: Prose inside the identity roots: commentary, bound by the whole-declaration
#: digest, never parsed as an identity (`_`-prefixed keys too). Never a
#: REQUIRED_IDENTITY field (`tools`, `permissions` and `public_requirements` are
#: identities; counter-model finding). The older exact-`UNKNOWN` rule
#: (`_unknown_leaves`) still covers every leaf under `shared` and `arms`.
PROSE_KEYS = frozenset({"provenance", "treatment", "verification", "rule", "removed_text"})


def _placeholder_leaves(value: object, where: str) -> list[str]:
    """Identity leaves holding a placeholder token (`PENDING`, `PROPOSED`,
    `UNKNOWN`) as a whole word anywhere in the value: `gpt-6-astra (PENDING)`
    is refused as surely as `PENDING`. Prose keys are skipped."""
    if isinstance(value, str):
        return [where] if _PLACEHOLDER.search(value) else []
    if isinstance(value, dict):
        return [p for k, v in value.items() if not (str(k).startswith("_") or k in PROSE_KEYS)
                for p in _placeholder_leaves(v, f"{where}.{k}")]
    if isinstance(value, list):
        return [p for i, v in enumerate(value) for p in _placeholder_leaves(v, f"{where}[{i}]")]
    return []


def _require_no_placeholders(data: Mapping[str, object]) -> None:
    found = [p for root in IDENTITY_ROOTS if root in data for p in _placeholder_leaves(data[root], root)]
    if found:
        raise _refuse(f"placeholder values still recorded at {found} ({'/'.join(PLACEHOLDER_MARKERS)}); "
                      "record the real value before approving a run")


def _require_agent_network(data: Mapping[str, object]) -> None:
    """#287 P3 (C4): the declaration is bound to provider-only egress (#442):
    `shared.agent_network` must name exactly the code's policy, allowlist
    digest and codex server-side-off flags. A later change to any of them
    needs a new approval (intended)."""
    from . import collection_conformance as cc
    from . import egress
    shared = data.get("shared")
    network = shared.get("agent_network") if isinstance(shared, dict) else None
    if not isinstance(network, dict):
        raise _refuse("shared.agent_network is required: this declaration must bind provider-only egress (#442)")
    expected = {"policy": cc.AGENT_NETWORK_POLICY, "allowlist_digest": egress.allowlist_digest(),
                "codex_server_side_off": list(egress.CODEX_SERVER_SIDE_OFF)}
    wrong = [k for k, v in expected.items() if network.get(k) != v]
    if wrong:
        raise _refuse(f"shared.agent_network {wrong} differ from the enforced provider-only egress "
                      f"{ {k: expected[k] for k in wrong} }")


#: #287 P3 (C5): path prefixes a run store must never sit under - most of the
#: #203-era live evidence was lost to run stores in /tmp scratchpads. A
#: heuristic, stated as one: an absolute path outside these is accepted.
_NON_DURABLE_PREFIXES = ("/tmp/", "/var/tmp/", "/dev/shm/")


def _refuse_non_durable(value: str, path: str) -> None:
    """Refuse a temp or scratchpad destination, checked on the path as written
    AND on its real filesystem destination (a symlinked ancestor counts)."""
    import os
    tmpdir = os.environ.get("TMPDIR")
    prefixes = _NON_DURABLE_PREFIXES + ((tmpdir.rstrip("/") + "/", os.path.realpath(tmpdir) + "/") if tmpdir else ())
    prefixes += tuple(os.path.realpath(p) + "/" for p in _NON_DURABLE_PREFIXES)
    for candidate in {path, os.path.realpath(path)} if path.startswith("/") else {path}:
        if any((candidate.rstrip("/") + "/").startswith(p) for p in prefixes) or "/scratchpad" in candidate:
            shown = repr(value) if candidate == value else f"{value!r} (resolves to {candidate!r})"
            raise _refuse(f"run_store {shown} is not durable (a temp directory or a session scratchpad); "
                          "evidence stored there is lost")


def _require_normal_form(label: str, path: str) -> None:
    """A path whose spelling is not its normal form (`..`, `.`, `//`) can name a
    forbidden directory that no prefix check sees (counter-model finding)."""
    import posixpath
    if path.startswith("//") or posixpath.normpath(path) != (path.rstrip("/") or "/"):
        raise _refuse(f"{label} {path!r} is not in normal form ('..', '.', or '//' components are refused)")


def _validate_run_store(value: object) -> str:
    """C5, the declared form: a literal leading `~/` (the running user's home;
    the approval digest binds that string, so no host path is committed) or an
    absolute path, in normal form. Checked at parse and approval, independent
    of who parses."""
    if not isinstance(value, str) or not value:
        raise _refuse("run_store must name a durable directory")
    if value.startswith("~"):
        if not value.startswith("~/"):
            raise _refuse(f"run_store {value!r}: only a leading '~/' (the running user's home) is accepted")
        _require_normal_form("run_store", "/home" + value[1:])
    elif not value.startswith("/"):
        raise _refuse(f"run_store {value!r} must be an absolute path or start with '~/'")
    else:
        _require_normal_form("run_store", value)
    _refuse_non_durable(value, value)
    return value


def resolve_run_store(value: object) -> Path:
    """C5, at launch: the declared run store expanded against this run's HOME
    (which must itself be absolute and in normal form), with the durability
    refusals applied to the EXPANDED path and its real destination, so a `~/`
    whose home is a temp directory is refused like `/tmp`."""
    import os
    declared = _validate_run_store(value)
    expanded = declared
    if declared.startswith("~/"):
        home = os.environ.get("HOME", "")
        if not home.startswith("/"):
            raise _refuse(f"run_store {declared!r} cannot be expanded: HOME is not an absolute path")
        _require_normal_form("HOME for run_store", home)
        expanded = home.rstrip("/") + declared[1:]
    _refuse_non_durable(declared, expanded)
    return Path(expanded)


_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")


def _require_image_identity(data: Mapping[str, object]) -> None:
    """C3, declared: a new-kind declaration names its image by tag, image ID
    and runtime receipt digest, all well formed. Without the receipt digest the
    run-time binding would have nothing to check (counter-model finding)."""
    shared = data.get("shared")
    image = shared.get("image") if isinstance(shared, Mapping) else None
    if not isinstance(image, Mapping):
        raise _refuse("shared.image is required: name the image tag, digest and receipt_sha256")
    tag = image.get("tag")
    if not isinstance(tag, str) or not tag:
        raise _refuse("shared.image.tag must name the image tag the run launches")
    for key in ("digest", "receipt_sha256"):
        if not isinstance(image.get(key), str) or not _SHA256.fullmatch(str(image.get(key))):
            raise _refuse(f"shared.image.{key} must be a 'sha256:<64 hex>' digest")


def _require_new_kind_bindings(data: Mapping[str, object]) -> None:
    """C4 and C5 for a declaration that must carry them: every discrimination
    declaration, and every calibration declaration with an outcome endpoint."""
    _require_agent_network(data)
    _require_image_identity(data)
    if "run_store" not in data:
        raise _refuse("run_store is required: name the durable directory this run's evidence is stored in")
    _validate_run_store(data.get("run_store"))


def load_declaration(path: Path) -> CalibrationDeclaration:
    return parse_declaration(json.loads(path.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class DiscriminationDeclaration:
    intact_subject: Mapping[str, object]
    degraded_subject: Mapping[str, object]
    mutation: Mapping[str, object]
    attempts_per_arm: int
    arm_order: tuple[str, ...]
    seed: int
    shared: Mapping[str, object]
    task_path: str
    grader_id: str
    grader_revision: str
    retain_transcripts: bool
    tolerance_non_evaluable_per_arm: int
    approval: Mapping[str, object] | None
    data: Mapping[str, object]
    task_fixture: str = "fixture"
    #: The declared obligation endpoint (#287 option 1), or None: the composite.
    endpoint: DiscriminationEndpoint | None = None


def _expected_degraded_revision(intact_subject: Mapping[str, object]) -> str:
    """The degraded arm's revision label, DERIVED from the intact subject's
    own pin, never typed - `degrade.py`'s own formula (`_degraded_revision`),
    called rather than copied, so the two cannot silently drift apart. A
    discrimination declaration states exactly ONE structured mutation
    (`MUTATION_KEYS`), so the location count is always 1; verified directly
    that the edit's skill/path/content play no part in this label (only the
    location COUNT and the base revision do) - that is what `mutated_digest`
    exists to cover instead (see `MUTATION_KEYS`'s comment)."""
    base = m.Source(
        kind="git", locator=str(intact_subject["locator"]), revision=str(intact_subject["revision"]),
        surface_dir=Path("."), digest="", origin=Path("."),
    )
    mutation = degrade.Mutation(edits=(degrade.FileEdit(skill="_", path="_", content=b"_"),))
    return degrade._degraded_revision(base, mutation)


def parse_discrimination_declaration(data: Mapping[str, object]) -> DiscriminationDeclaration:
    """skillc#287's discrimination test (intact vs degraded): validates the
    shape ADR 0005 needs fixed before any attempt - task, schedule,
    tolerance, arm order, the mutation's own identity - without going
    through `parse_declaration`, which structurally cannot express this
    contrast (see `DISCRIMINATION_KIND`'s comment). Reuses `parse_
    declaration`'s own shared/attempts/arm_order/task machinery via
    `_parse_schedule_and_identities`, never a copy of it."""
    if data.get("kind") != DISCRIMINATION_KIND:
        raise _refuse(f"kind is {data.get('kind')!r}, not {DISCRIMINATION_KIND!r}")
    if {"outcome_endpoint", "task_content"} & data.keys():
        raise _refuse("discrimination cannot use improvement outcome_endpoint/task_content fields")
    arms_raw = data.get("arms")
    if not isinstance(arms_raw, list) or len(arms_raw) != 2 or not all(isinstance(a, dict) for a in arms_raw):
        raise _refuse("exactly two arms are declared: 'intact' and 'degraded'")
    by_name = {a.get("name"): a for a in arms_raw}
    if set(by_name) != set(DISCRIMINATION_ARMS):
        raise _refuse(f"arms must be named exactly {sorted(DISCRIMINATION_ARMS)}, got "
                      f"{sorted(str(n) for n in by_name)}")
    intact_arm, degraded_arm = by_name["intact"], by_name["degraded"]

    intact_subject = intact_arm.get("subject")
    if not isinstance(intact_subject, dict) or not all(
            isinstance(intact_subject.get(k), str) and intact_subject.get(k)
            for k in ("name", "locator", "revision")):
        raise _refuse("arm 'intact' needs a subject naming name, locator and revision")
    _validated_subject_profile(intact_subject, "arm 'intact'.subject")

    degraded_subject = degraded_arm.get("subject")
    if not isinstance(degraded_subject, dict) or not all(
            isinstance(degraded_subject.get(k), str) and degraded_subject.get(k)
            for k in ("name", "locator", "revision")):
        raise _refuse("arm 'degraded' needs a subject naming name, locator and revision")
    if set(degraded_subject) != set(intact_subject):
        extra = sorted(set(degraded_subject) ^ set(intact_subject))
        raise _refuse(f"arm 'degraded' subject carries {extra} that 'intact' does not, or vice versa; a "
                      "discrimination contrast is the SAME subject, mutated - every key but revision must "
                      "match exactly, whatever keys a future subject dict grows")
    mismatched_identity = [k for k in intact_subject
                           if k != "revision" and degraded_subject.get(k) != intact_subject.get(k)]
    if mismatched_identity:
        raise _refuse(f"arm 'degraded' names a different subject {mismatched_identity} than 'intact'; "
                      "a discrimination contrast is the SAME subject, mutated - not a different one")

    mutation = degraded_arm.get("mutation")
    if not isinstance(mutation, dict) or set(mutation) != MUTATION_KEYS \
            or not all(isinstance(mutation.get(k), str) and mutation.get(k) for k in MUTATION_KEYS):
        raise _refuse(f"arm 'degraded' needs a 'mutation' naming exactly {sorted(MUTATION_KEYS)}, each a "
                      "non-empty string - diagnose_evidence is not optional: without it, nothing shows "
                      "that no other installed skill or helper still carries what this removes")
    if not _SHA256_DIGEST_RE.fullmatch(mutation["mutated_digest"]):
        raise _refuse(f"mutation.mutated_digest must be 'sha256:' + 64 lowercase hex characters, not "
                      f"{mutation['mutated_digest']!r}")

    expected_revision = _expected_degraded_revision(intact_subject)
    if degraded_subject["revision"] != expected_revision:
        raise _refuse(f"arm 'degraded' subject.revision is {degraded_subject['revision']!r}, not the derived "
                      f"{expected_revision!r} - a hand-typed label is not a recorded mutation")

    if "run_store" in data:
        _validate_run_store(data.get("run_store"))
    tolerance = data.get("tolerance")
    non_evaluable = tolerance.get("non_evaluable_per_arm") if isinstance(tolerance, dict) else None
    if isinstance(non_evaluable, bool) or not isinstance(non_evaluable, int) or non_evaluable < 1:
        raise _refuse("tolerance.non_evaluable_per_arm must be a positive integer, fixed before any attempt runs")

    fields = _parse_schedule_and_identities(data, list(DISCRIMINATION_ARMS))
    return DiscriminationDeclaration(
        intact_subject=dict(intact_subject), degraded_subject=dict(degraded_subject), mutation=dict(mutation),
        attempts_per_arm=fields.attempts_per_arm, arm_order=fields.sequence, seed=fields.seed,
        shared=fields.shared, task_path=fields.task_path, grader_id=fields.grader_id,
        grader_revision=fields.grader_revision, retain_transcripts=True,
        tolerance_non_evaluable_per_arm=non_evaluable, approval=fields.approval, data=dict(data),
        task_fixture=fields.task_fixture, endpoint=_discrimination_endpoint(data),
    )


def require_degraded_mutation(intact_bytes: bytes, mutation: Mapping[str, object]) -> bytes:
    """The run-time mutation check (#287 P2): the degraded file a discrimination
    run installs is derived from the ACQUIRED intact file's bytes, and must be
    the exact file the approval and P1's textual scan describe. `removed_text`
    must occur EXACTLY once (zero means the declared mutation does not apply to
    these bytes; more than one means removing "it" is ambiguous), and the bytes
    with it removed must hash to `mutation.mutated_digest`. Returns those
    degraded bytes; refuses otherwise.

    This is what binds `mutation.skill`/`path` to real content: an approval's
    `mutated_digest` alone names a digest, not which file produced it."""
    removed = mutation.get("removed_text")
    declared = mutation.get("mutated_digest")
    if not isinstance(removed, str) or not removed or not isinstance(declared, str):
        raise _refuse("mutation must name a non-empty removed_text and a mutated_digest")
    needle = removed.encode("utf-8")
    count = intact_bytes.count(needle)
    if count != 1:
        raise _refuse(f"mutation.removed_text occurs {count} time(s) in the acquired intact "
                      f"{mutation.get('skill')}/{mutation.get('path')}, not exactly once; the declared "
                      f"mutation does not describe these bytes")
    degraded = intact_bytes.replace(needle, b"", 1)
    measured = trial.sha256_bytes(degraded)
    if measured != declared:
        raise _refuse(f"the degraded {mutation.get('skill')}/{mutation.get('path')} hashes to {measured}, not "
                      f"the declared mutated_digest {declared}; refusing a degraded arm other than the approved one")
    return degraded


def load_discrimination_declaration(path: Path) -> DiscriminationDeclaration:
    return parse_discrimination_declaration(json.loads(path.read_text(encoding="utf-8")))


def _unknown_leaves(value: object, where: str) -> list[str]:
    if value == UNKNOWN:
        return [where]
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in _unknown_leaves(v, f"{where}.{k}")]
    if isinstance(value, list):
        return [p for i, v in enumerate(value) for p in _unknown_leaves(v, f"{where}[{i}]")]
    return []


#: The identity fields that must hold a real, non-empty value before a run is
#: authorized - each a path into the declaration ("treatment" is the first
#: non-baseline arm; a third arm installs the same subject, by
#: `parse_declaration`). Checked by presence, not only by the absence of the
#: literal `UNKNOWN`: an empty object or a null carries no identity either
#: (counter-model review).
REQUIRED_IDENTITIES: tuple[tuple[str, ...], ...] = (
    ("shared", "client", "name"), ("shared", "client", "version"),
    ("shared", "model"), ("shared", "reasoning_effort"),
    ("shared", "image", "tag"), ("shared", "image", "digest"),
    ("shared", "tools"), ("shared", "permissions"), ("shared", "public_requirements"),
    ("treatment", "subject", "name"), ("treatment", "subject", "locator"),
    ("treatment", "subject", "revision"),
)


def _treated_arm(declaration: CalibrationDeclaration) -> dict[str, object] | None:
    """The first non-baseline arm - `calibration-declaration`'s own
    "treatment" identity path, factored out so `_identity_at` and
    `require_approved`'s profile-opt-in check (#334) read the same arm."""
    arms = declaration.data.get("arms")
    return next((a for a in arms if isinstance(a, dict) and a.get("name") != BASELINE_ARM), None) \
        if isinstance(arms, list) else None


def _identity_at(declaration: CalibrationDeclaration, path: tuple[str, ...]) -> object:
    node: object
    if path[0] == "treatment":
        node = _treated_arm(declaration)
    else:
        node = declaration.data.get(path[0])
    for key in path[1:]:
        node = node.get(key) if isinstance(node, dict) else None
    return node


def _require_schedule_approval(approval: Mapping[str, object] | None, attempts_per_arm: int) -> Mapping[str, object]:
    """#323: `approval` must record who/when and the exact schedule size
    approved - checked as its own field, not inferred from `approval.scope`'s
    prose. Without this, raising #323's own `MAX_ATTEMPTS_PER_ARM` opened a
    gap this check did not previously need to close: a parser already
    refuses an `attempts_per_arm` whose `arm_order.sequence` was not
    re-derived from it, but a declaration edited to change BOTH
    `attempts_per_arm` and a freshly re-derived `arm_order` together is
    internally self-consistent and would otherwise sail through on an
    approval that was never asked about the new size - exactly the
    "approved manifest eligible for a different run" ADR 0005 forbids.
    Shared by every declaration kind's `require_approved*`."""
    if not approval or not all(isinstance(approval.get(k), str) and approval.get(k) for k in ("by", "at")):
        raise _refuse("not approved: 'approval' must record who approved it ('by') and when ('at') "
                      "before any attempt runs (ADR 0005)")
    approved_attempts = approval.get("attempts_per_arm")
    if isinstance(approved_attempts, bool) or not isinstance(approved_attempts, int):
        raise _refuse("not approved: 'approval.attempts_per_arm' must record the exact schedule size "
                      "approved, as an integer - a declaration edited to a different size afterward "
                      "must be refused as unapproved, not silently re-matched by prose alone")
    if approved_attempts != attempts_per_arm:
        raise _refuse(f"approved for attempts_per_arm={approved_attempts}, not the declared "
                      f"{attempts_per_arm}; a changed schedule needs its own approval")
    return approval


def _require_grader_matches(root: Path, task_path: str, grader_id: str, grader_revision: str) -> None:
    """The declared task's grader is the one on disk - shared by every
    declaration kind's `require_approved*`."""
    grader = verify.GraderDef.load(root / task_path)
    if (grader.id, grader.revision) != (grader_id, grader_revision):
        raise _refuse(f"the task's grader is {grader.id!r} revision {grader.revision!r}, not the declared "
                      f"{grader_id!r} revision {grader_revision!r}")


def _require_task_fixture(root: Path, task_path: str, task_fixture: str, approval: Mapping[str, object]) -> None:
    """task.fixture (#287) is an approval-bound identity - an approval
    covers exactly one tree, the same #323 pattern `attempts_per_arm`/
    `mutated_digest`/`profile_inventory_digest` already use. The tree must
    exist on disk (a declaration naming a fixture nobody committed cannot
    be run), and the approval must name the SAME fixture, defaulting to
    "fixture" when the approval predates this field - every already-
    approved manifest named no other tree, so it stays valid unchanged;
    only a declaration asking for a NON-default tree needs an approval
    that says so explicitly. Shared by every declaration kind's
    `require_approved*`, alongside `_require_grader_matches`, which is why
    it takes the same `root`/`task_path`."""
    fixture_dir = root / task_path / task_fixture
    if not fixture_dir.is_dir():
        raise _refuse(f"task.fixture {task_fixture!r} does not exist under {task_path!r} ({fixture_dir})")
    approved_fixture = approval.get("task_fixture", "fixture")
    if approved_fixture != task_fixture:
        raise _refuse(f"approved for task.fixture={approved_fixture!r}, not the declared {task_fixture!r}; "
                      "a changed fixture tree needs its own approval")


def _require_profile_approval(subject: Mapping[str, object], approval: Mapping[str, object], root: Path) -> None:
    """skillc#334: when `subject.profile` names a validated profile, the
    approval must record `profile_inventory_digest` matching the
    COMMITTED inventory evidence at that path - an approval binds to one
    exact closure, exactly as #323 binds `attempts_per_arm`. A no-op when
    `subject.profile` is absent (today's behavior: selected skill files
    only, nothing to bind). This checks the APPROVAL's binding against
    the repo's committed evidence file only - it is NOT the live
    re-validation against the subject's actual current source (that runs
    later, against a real acquisition, and is a separate precondition of
    every live attempt, not of approval)."""
    profile_path = subject.get("profile")
    if profile_path is None:
        return
    approved_digest = approval.get("profile_inventory_digest")
    if not isinstance(approved_digest, str) or not approved_digest:
        raise _refuse(
            "not approved: 'approval.profile_inventory_digest' must record the exact closure digest "
            "approved, as a non-empty string - subject.profile names a profile but no closure was ever "
            "approved for it"
        )
    inventory_path = root / str(profile_path) / "evidence" / "inventory.json"
    try:
        committed = json.loads(inventory_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise _refuse(f"subject.profile {profile_path!r} names no readable evidence/inventory.json: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise _refuse(f"{inventory_path} is not valid JSON: {exc}") from exc
    if not isinstance(committed, dict):
        raise _refuse(f"{inventory_path} does not parse as a JSON object")
    committed_digest = profile.inventory_digest(committed)
    if approved_digest != committed_digest:
        raise _refuse(
            f"approved for profile_inventory_digest={approved_digest!r}, but the committed inventory at "
            f"{inventory_path} is now {committed_digest!r} - the profile's evidence changed since approval "
            f"and needs its own approval"
        )


def require_approved(declaration: CalibrationDeclaration, root: Path) -> None:
    """Refuse to authorize a run of this declaration unless its approval is
    recorded (who and when, and the exact schedule size approved), every
    `REQUIRED_IDENTITIES` field holds a real value, no identity anywhere
    still says `UNKNOWN`, and the declared task's grader is the one on disk.
    A declaration that validates is still only a plan (ADR 0005)."""
    approval = _require_schedule_approval(declaration.approval, declaration.attempts_per_arm)
    require_outcome_approval(declaration)
    treated = _treated_arm(declaration)
    treated_subject = treated.get("subject") if treated is not None else None
    if isinstance(treated_subject, dict):
        _require_profile_approval(treated_subject, approval, root)
    absent = [".".join(path) for path in REQUIRED_IDENTITIES
              if not (isinstance(v := _identity_at(declaration, path), str) and v.strip() and v != UNKNOWN)]
    if absent:
        raise _refuse(f"identities not recorded: {absent}; record them before approving a run")
    arms = declaration.data.get("arms")
    unknown = _unknown_leaves(declaration.shared, "shared") + _unknown_leaves(
        arms if isinstance(arms, list) else [], "arms")
    if unknown:
        raise _refuse(f"identities still UNKNOWN: {unknown}; record them before approving a run")
    _require_no_placeholders(declaration.data)
    if outcome_endpoint(declaration) is not None:
        _require_new_kind_bindings(declaration.data)
    _require_grader_matches(root, declaration.task_path, declaration.grader_id, declaration.grader_revision)
    _require_task_fixture(root, declaration.task_path, declaration.task_fixture, approval)
    endpoint = outcome_endpoint(declaration)
    if endpoint is not None:
        grader = verify.GraderDef.load(root / declaration.task_path)
        if set(endpoint.criteria) - set(grader.criteria):
            raise _refuse("outcome_endpoint selects criteria absent from the declared grader")
    # Last, as the backstop every narrower check above sits in front of: any
    # field changed after approval that no specific check names still fails here.
    _require_whole_declaration_approval(declaration.data, approval)


#: skillc#287: a discrimination declaration's own identity fields - parallel
#: to `REQUIRED_IDENTITIES`, which is `calibration-declaration`'s baseline/
#: treatment shape and does not apply here (neither arm is `BASELINE_ARM`).
REQUIRED_IDENTITIES_DISCRIMINATION: tuple[tuple[str, ...], ...] = (
    ("shared", "client", "name"), ("shared", "client", "version"),
    ("shared", "model"), ("shared", "reasoning_effort"),
    ("shared", "image", "tag"), ("shared", "image", "digest"),
    ("shared", "tools"), ("shared", "permissions"), ("shared", "public_requirements"),
    ("intact", "subject", "name"), ("intact", "subject", "locator"), ("intact", "subject", "revision"),
    ("degraded", "subject", "name"), ("degraded", "subject", "locator"), ("degraded", "subject", "revision"),
    ("degraded", "mutation", "skill"), ("degraded", "mutation", "path"),
    ("degraded", "mutation", "removed_text"), ("degraded", "mutation", "diagnose_evidence"),
    ("degraded", "mutation", "mutated_digest"),
)


def _identity_at_discrimination(declaration: DiscriminationDeclaration, path: tuple[str, ...]) -> object:
    node: object
    if path[0] in DISCRIMINATION_ARMS:
        arms_raw = declaration.data.get("arms")
        node = next((a for a in arms_raw if isinstance(a, dict) and a.get("name") == path[0]), None) \
            if isinstance(arms_raw, list) else None
    else:
        node = declaration.data.get(path[0])
    for key in path[1:]:
        node = node.get(key) if isinstance(node, dict) else None
    return node


def require_discrimination_approval_record(declaration: DiscriminationDeclaration) -> None:
    """The PURE part of discrimination approval - no disk reads - so a report
    can re-check a stored launch snapshot without the current checkout's
    grader, fixture or profile files changing the answer: who/when and the
    schedule size, the approved mutated_digest, and (D-P2a) the whole
    declaration digest."""
    approval = _require_schedule_approval(declaration.approval, declaration.attempts_per_arm)
    if approval.get("mutated_digest") != declaration.mutation.get("mutated_digest"):
        raise _refuse("approval.mutated_digest does not match the declared mutation")
    _require_whole_declaration_approval(declaration.data, approval)


def require_approved_discrimination(declaration: DiscriminationDeclaration, root: Path) -> None:
    """The discrimination-declaration counterpart to `require_approved`:
    the same approval/identity/grader-on-disk checks, against this kind's
    own identity paths (`REQUIRED_IDENTITIES_DISCRIMINATION`) rather than
    the baseline/treatment shape that does not exist here - plus one check
    `require_approved` has no counterpart for: `approval.mutated_digest`
    must equal the declared mutation's own `mutated_digest` (the same
    #323 pattern as `attempts_per_arm`, applied to the OTHER thing that can
    change after approval without changing the schedule size: a different
    `removed_text` on the same file produces a different degraded file,
    hence a different `mutated_digest`, and an approval is for one exact
    degraded file, never "whatever this field says now")."""
    approval = _require_schedule_approval(declaration.approval, declaration.attempts_per_arm)
    approved_digest = approval.get("mutated_digest")
    declared_digest = declaration.mutation.get("mutated_digest")
    if approved_digest != declared_digest:
        raise _refuse(f"approved for mutation.mutated_digest={approved_digest!r}, not the declared "
                      f"{declared_digest!r}; a changed mutation needs its own approval")
    _require_profile_approval(declaration.intact_subject, approval, root)
    absent = [".".join(path) for path in REQUIRED_IDENTITIES_DISCRIMINATION
              if not (isinstance(v := _identity_at_discrimination(declaration, path), str)
                      and v.strip() and v != UNKNOWN)]
    if absent:
        raise _refuse(f"identities not recorded: {absent}; record them before approving a run")
    arms = declaration.data.get("arms")
    unknown = _unknown_leaves(declaration.shared, "shared") + _unknown_leaves(
        arms if isinstance(arms, list) else [], "arms")
    if unknown:
        raise _refuse(f"identities still UNKNOWN: {unknown}; record them before approving a run")
    _require_no_placeholders(declaration.data)
    _require_new_kind_bindings(declaration.data)
    _require_grader_matches(root, declaration.task_path, declaration.grader_id, declaration.grader_revision)
    require_discrimination_endpoint_criteria(declaration, root)
    _require_task_fixture(root, declaration.task_path, declaration.task_fixture, approval)
    _require_whole_declaration_approval(declaration.data, approval)  # the backstop, as in require_approved


def require_discrimination_endpoint_criteria(declaration: DiscriminationDeclaration, root: Path) -> None:
    """A declared obligation endpoint names criteria the task's grader ON DISK
    actually has; a misspelt or retired criterion would score every attempt
    INCONCLUSIVE, which reads as an agent problem."""
    if declaration.endpoint is None:
        return
    known = {str(c) for c in verify.GraderDef.load(root / declaration.task_path).criteria}
    missing = sorted(set(declaration.endpoint.criteria) - known)
    if missing:
        raise _refuse(f"discrimination_endpoint names criteria the grader does not have: {missing}")


def validate_expanded_instruction_lane(declaration: CalibrationDeclaration, root: Path) -> None:
    """The expanded-instruction lane's file-backed checks (protocol.md
    10.4), none of which `parse_declaration` can do without reading a file.
    A no-op on every other lane - nothing here is this lane's business.

    0. SUBJECT BINDING (codex review). The inventory must be read as a
    `skillc profile validate` output addressed to THIS declaration's
    subject - checked against the inventory's own `subject.locator`/
    `subject.revision`, which `profile.validate` always records. This does
    not re-run `profile.validate` (out of this function's bounded scope,
    #274) or cryptographically prove the file was not fabricated; it closes
    the cheap version of that gap - an inventory that doesn't even CLAIM to
    be for the declared subject - and is why every field below is read with
    an explicit type/presence check rather than `.get(..., default)`: an
    absent or malformed field must refuse, never silently pass as empty.

    1. HELPER PARITY. Must have validated at `treatment_question == "prose"`
    - never `product`, which permits treatment-scoped helpers the E arm
    would then lack, exactly the confound this check exists to rule out
    (orchestrator review, #274). `helper_parity.treatment` must be PRESENT
    as a list and empty - absent entirely is refused, not read as empty
    (codex review: `.get(\"helper_parity\", {}).get(\"treatment\")` let an
    inventory with no helper_parity object at all pass, indistinguishable
    from one that validated and genuinely found nothing).

    2. CONTENT IDENTITY. E's `instruction` (the inlined obligation text)
    must hash to the SAME `body_digest` the inventory recorded for the one
    skill S names. Byte-identical, not merely equivalent: the lane's own
    "restate, never add" rule (protocol.md 10.1) is satisfied by
    construction when the bytes do not differ at all."""
    if declaration.lane != EXPANDED_INSTRUCTION_LANE:
        return
    arms_raw = declaration.data.get("arms")
    treated = [a for a in (arms_raw if isinstance(arms_raw, list) else [])
              if isinstance(a, dict) and a.get("name") != BASELINE_ARM]
    s_arm = next(a for a in treated if PROVIDED_KEYS <= set(a))
    e_arm = next(a for a in treated if a is not s_arm)
    inventory_path = root / str(s_arm["inventory"])
    try:
        inventory_raw = json.loads(inventory_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise _refuse(f"inventory {inventory_path} could not be read: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise _refuse(f"inventory {inventory_path} is not valid JSON: {exc}") from exc
    if not isinstance(inventory_raw, dict):
        raise _refuse(f"inventory {inventory_path} is not a JSON object")
    inventory: dict[str, object] = inventory_raw

    inv_subject = inventory.get("subject")
    declared_subject = s_arm.get("subject")
    if not isinstance(inv_subject, dict) or not isinstance(declared_subject, dict):
        raise _refuse(f"inventory {inventory_path} carries no 'subject' record to bind against the "
                      f"declared one")
    mismatched = [k for k in ("locator", "revision") if inv_subject.get(k) != declared_subject.get(k)]
    if mismatched:
        raise _refuse(f"inventory {inventory_path} was validated for subject {inv_subject.get('locator')!r} "
                      f"@ {inv_subject.get('revision')!r}, not the declared "
                      f"{declared_subject.get('locator')!r} @ {declared_subject.get('revision')!r} ({mismatched})")

    question = inventory.get("treatment_question")
    if question != "prose":
        raise _refuse(f"inventory {inventory_path} validated at treatment_question {question!r}, not "
                      f"'prose' - the expanded-instruction lane needs identical helpers in every arm, "
                      f"which only a prose question proves (protocol.md 10.4)")

    helper_parity = inventory.get("helper_parity")
    if not isinstance(helper_parity, dict) or "treatment" not in helper_parity:
        raise _refuse(f"inventory {inventory_path} carries no helper_parity.treatment field - absence is "
                      f"not evidence of an empty population, it means no parity evidence was supplied")
    treatment_scoped = helper_parity["treatment"]
    if not isinstance(treatment_scoped, list):
        raise _refuse(f"inventory {inventory_path}'s helper_parity.treatment is not a list: {treatment_scoped!r}")
    if treatment_scoped:
        raise _refuse(f"inventory {inventory_path} carries treatment-scoped helper(s) {treatment_scoped} "
                      f"despite a prose treatment_question - this inventory is stale or was tampered "
                      f"with after `skillc profile validate` ran")

    skill_name = s_arm["named_skills"][0]
    skills = inventory.get("skills")
    if not isinstance(skills, list):
        raise _refuse(f"inventory {inventory_path} carries no 'skills' list")
    matching = next((s for s in skills if isinstance(s, dict) and s.get("name") == skill_name), None)
    if not isinstance(matching, dict) or not isinstance(matching.get("body_digest"), str):
        raise _refuse(f"inventory {inventory_path} has no skill named {skill_name!r} with a body_digest "
                      f"(named by arm {s_arm['name']!r})")
    actual = m.sha256_bytes(str(e_arm["instruction"]).encode("utf-8"))
    if actual != matching["body_digest"]:
        raise _refuse(f"arm {e_arm['name']!r}: instruction digest {actual} does not match {skill_name!r}'s "
                      f"body_digest {matching['body_digest']!r} - the inlined text must restate the skill's "
                      f"body byte-for-byte, never a paraphrase (protocol.md 10.1)")


def arm_spec(declaration: CalibrationDeclaration, name: str) -> Mapping[str, object]:
    """The declared arm called `name` (`parse_declaration` proved names are
    distinct)."""
    arms = declaration.data.get("arms")
    for arm in arms if isinstance(arms, list) else []:
        if isinstance(arm, dict) and arm.get("name") == name:
            return arm
    raise _refuse(f"no arm named {name!r}")
