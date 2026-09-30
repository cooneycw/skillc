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
exactly two arms that differ only in their treatment (every other identity
lives once, under `shared`), 3-5 attempts per arm, and an arm order derived
from a recorded seed rather than chosen by hand. A declaration is not an
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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import records, verify

#: The criteria the primary endpoint never reads, whatever a record carries.
PRIMARY_ENDPOINT_EXCLUDES = frozenset({verify.READINESS_CRITERION})

#: The status of an attempt no grade exists for. Not a protocol status: the
#: attempt never reached the endpoint, and it is reported, never dropped.
NOT_GRADED = "NOT_GRADED"

BASELINE_ARM = "baseline"
MIN_ATTEMPTS_PER_ARM, MAX_ATTEMPTS_PER_ARM = 3, 5
UNKNOWN = "UNKNOWN"

#: The only keys an arm may carry. Anything else - a model, an effort, a
#: timeout - would be a second difference between the arms; it belongs under
#: `shared`, once, for both.
ARM_KEYS = frozenset({"name", "subject", "treatment"})

#: What both arms must share, by construction (issue #204's Scope).
SHARED_KEYS = frozenset({
    "client", "model", "reasoning_effort", "tools", "permissions", "public_requirements",
    "image", "per_attempt_seconds", "total_seconds",
})


class DeclarationRefused(ValueError):
    """The calibration declaration is not one a run could honestly follow."""


def primary_endpoint(record: Mapping[str, object]) -> dict[str, object]:
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


def _refuse(message: str) -> DeclarationRefused:
    return DeclarationRefused(f"calibration declaration: {message}")


def _positive_number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value) or value <= 0:
        raise _refuse(f"{what} must be a positive, finite number of seconds, not {value!r}")
    return float(value)


def parse_declaration(data: Mapping[str, object]) -> CalibrationDeclaration:
    """Validate a declaration's shape. See the module docstring for what it
    requires and why; every refusal names the field."""
    if data.get("kind") != "calibration-declaration":
        raise _refuse(f"kind is {data.get('kind')!r}, not 'calibration-declaration'")
    arms_raw = data.get("arms")
    if not isinstance(arms_raw, list) or len(arms_raw) != 2 or not all(isinstance(a, dict) for a in arms_raw):
        raise _refuse("exactly two arms are declared (full treatment versus minimal baseline); "
                      "an ablation belongs to #203, not to calibration")
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
    if len(set(names)) != 2 or BASELINE_ARM not in names:
        raise _refuse(f"arms must be two distinct names, one of them {BASELINE_ARM!r}; got {names}")
    baseline = next(a for a in arms_raw if a["name"] == BASELINE_ARM)
    treatment = next(a for a in arms_raw if a["name"] != BASELINE_ARM)
    if baseline.get("subject") is not None:
        raise _refuse("the baseline arm installs nothing: its subject is null")
    if not isinstance(treatment.get("subject"), dict):
        raise _refuse(f"arm {treatment['name']!r} names no subject to install")

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
    if total < per_attempt * attempts * 2:
        raise _refuse(f"shared.total_seconds {total:g} cannot cover {attempts * 2} attempts of "
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
    if data.get("retain_transcripts") is not True:
        raise _refuse("retain_transcripts must be true: report question 4 is answered from transcripts (#202)")
    approval = data.get("approval")
    if approval is not None and not isinstance(approval, dict):
        raise _refuse("approval is null (not yet approved) or an object recording who approved and when")

    return CalibrationDeclaration(
        arms=tuple(names), attempts_per_arm=attempts, arm_order=tuple(sequence), seed=seed,
        shared=dict(shared), task_path=str(task["path"]), grader_id=str(task["grader_id"]),
        grader_revision=str(task["grader_revision"]), retain_transcripts=True, approval=approval,
        data=dict(data),
    )


def load_declaration(path: Path) -> CalibrationDeclaration:
    return parse_declaration(json.loads(path.read_text(encoding="utf-8")))


def _unknown_leaves(value: object, where: str) -> list[str]:
    if value == UNKNOWN:
        return [where]
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in _unknown_leaves(v, f"{where}.{k}")]
    if isinstance(value, list):
        return [p for i, v in enumerate(value) for p in _unknown_leaves(v, f"{where}[{i}]")]
    return []


#: The identity fields that must hold a real, non-empty value before a run is
#: authorized - each a path into the declaration ("treatment" is the
#: non-baseline arm). Checked by presence, not only by the absence of the
#: literal `UNKNOWN`: an empty object or a null carries no identity either
#: (counter-model review).
REQUIRED_IDENTITIES: tuple[tuple[str, ...], ...] = (
    ("shared", "client", "name"), ("shared", "client", "version"),
    ("shared", "model"), ("shared", "reasoning_effort"),
    ("shared", "image", "tag"), ("shared", "image", "digest"),
    ("treatment", "subject", "name"), ("treatment", "subject", "locator"),
    ("treatment", "subject", "revision"),
)


def _identity_at(declaration: CalibrationDeclaration, path: tuple[str, ...]) -> object:
    node: object
    if path[0] == "treatment":
        arms = declaration.data.get("arms")
        node = next((a for a in arms if isinstance(a, dict) and a.get("name") != BASELINE_ARM),
                    None) if isinstance(arms, list) else None
    else:
        node = declaration.data.get(path[0])
    for key in path[1:]:
        node = node.get(key) if isinstance(node, dict) else None
    return node


def require_approved(declaration: CalibrationDeclaration, root: Path) -> None:
    """Refuse to authorize a run of this declaration unless its approval is
    recorded (who and when), every `REQUIRED_IDENTITIES` field holds a real
    value, no identity anywhere still says `UNKNOWN`, and the declared task's
    grader is the one on disk. A declaration that validates is still only a
    plan (ADR 0005)."""
    approval = declaration.approval
    if not approval or not all(isinstance(approval.get(k), str) and approval.get(k) for k in ("by", "at")):
        raise _refuse("not approved: 'approval' must record who approved it ('by') and when ('at') "
                      "before any attempt runs (ADR 0005)")
    absent = [".".join(path) for path in REQUIRED_IDENTITIES
              if not (isinstance(v := _identity_at(declaration, path), str) and v.strip() and v != UNKNOWN)]
    if absent:
        raise _refuse(f"identities not recorded: {absent}; record them before approving a run")
    arms = declaration.data.get("arms")
    unknown = _unknown_leaves(declaration.shared, "shared") + _unknown_leaves(
        arms if isinstance(arms, list) else [], "arms")
    if unknown:
        raise _refuse(f"identities still UNKNOWN: {unknown}; record them before approving a run")
    grader = verify.GraderDef.load(root / declaration.task_path)
    if (grader.id, grader.revision) != (declaration.grader_id, declaration.grader_revision):
        raise _refuse(f"the task's grader is {grader.id!r} revision {grader.revision!r}, not the declared "
                      f"{declaration.grader_id!r} revision {declaration.grader_revision!r}")
