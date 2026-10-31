"""Offline verdicts over controller-held live wave captures (#620).

No launch, filesystem discovery, model call or inference from agent prose occurs
here. The caller freezes role bindings before protocol observation, captures
complete streams and artifacts, and supplies the independent delivery grader.
DockerWave's lifecycle-only report is not a task-success certificate.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypeGuard

Verdict = Literal["PASS", "FAIL", "UNKNOWN"]


def _number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


@dataclass(frozen=True)
class RoleBinding:
    role: str
    attempt_id: str
    session_id: str | None
    task: str
    generation: int
    revision: int
    nonce: str
    required_artifacts: tuple[str, ...]


@dataclass(frozen=True)
class WavePlan:
    wave_id: str
    roles: tuple[RoleBinding, ...]
    integrator: str
    deadline: float

    def __post_init__(self) -> None:
        names = [r.role for r in self.roles]
        sessions = [r.session_id for r in self.roles if r.session_id is not None]
        attempts = [r.attempt_id for r in self.roles]
        if (not self.wave_id or not self.roles or len(set(names)) != len(names)
                or len(set(attempts)) != len(attempts) or len(set(sessions)) != len(sessions)
                or self.integrator not in names or not _number(self.deadline) or self.deadline == 0):
            raise ValueError("invalid planned wave")
        for r in self.roles:
            if (any(not isinstance(v, str) or not v for v in (r.role, r.attempt_id, r.task, r.nonce))
                    or (r.session_id is not None and not r.session_id)
                    or type(r.generation) is not int or r.generation < 0
                    or type(r.revision) is not int or r.revision < 1
                    or not r.required_artifacts or len(set(r.required_artifacts)) != len(r.required_artifacts)
                    or any(not isinstance(p, str) or not p for p in r.required_artifacts)):
                raise ValueError("invalid declared role binding")


@dataclass(frozen=True)
class Blob:
    """Bytes and their digest from the controller's immutable capture inventory."""

    data: bytes
    sha256: str

    def valid(self) -> bool:
        return hashlib.sha256(self.data).hexdigest() == self.sha256


@dataclass(frozen=True)
class PokeCount:
    role: str
    session_id: str
    pokes: int | None


@dataclass(frozen=True)
class RoleEvidence:
    role: str
    attempt_id: str
    session_id: str | None
    transcript: Blob | None
    protocol: Blob | None
    artifacts: Mapping[str, Blob] | None
    pokes: PokeCount | None
    started: bool
    capture_complete: bool
    stopped: bool
    cleanup_confirmed: bool
    stop_reason: str
    exit_code: int | None
    stop_elapsed: float | None = None
    tokens: int | None = None
    wall_seconds: float | None = None


@dataclass(frozen=True)
class WaveEvidence:
    wave_id: str
    roles: tuple[RoleEvidence, ...]
    completion_elapsed: float | None
    cleanup_confirmed: bool
    # Relative times use the SAME common monotonic origin as event elapsed.
    infrastructure_failed_at: float | None = None
    deadline_witnessed_at: float | None = None
    abandonment: bool | None = None
    handoff_timings: Mapping[str, float] | None = None
    clutter_count: int | None = None


@dataclass(frozen=True)
class DeliveryGrade:
    status: Verdict
    completed_elapsed: float | None
    reasons: tuple[str, ...] = ()


ArtifactGrader = Callable[[WavePlan, Mapping[str, Mapping[str, bytes]]], DeliveryGrade]


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _jsonl(blob: Blob | None) -> list[dict[str, Any]]:
    if blob is None or not blob.valid() or not blob.data or not blob.data.endswith(b"\n"):
        raise ValueError("missing, corrupt or truncated capture")
    rows = [json.loads(line, object_pairs_hook=_unique) for line in blob.data.splitlines()]
    if not rows or any(not isinstance(r, dict) for r in rows):
        raise ValueError("invalid capture rows")
    return rows


def verdict(plan: WavePlan, evidence: WaveEvidence | None, grade: ArtifactGrader) -> dict[str, Any]:
    """Positive observed violations survive unrelated missing evidence.

    Capture loss never proves bad delivery. In particular, infrastructure
    cancellation does not synthesize incomplete-work, timeout or exit failures.
    Protocol events are controller observations, never parsed acknowledgements
    in an agent's transcript. Final report emission is outside the boundary.
    """
    failures: set[str] = set()
    unknown: set[str] = set()
    diagnostics: dict[str, Any] = {}
    artifacts: dict[str, dict[str, bytes]] = {}
    last_event = 0.0
    if evidence is not None and evidence.wave_id != plan.wave_id:
        unknown.add("wave-capture-binding")
        evidence = None
    infra = evidence.infrastructure_failed_at if evidence else None
    infra_unknown = bool(evidence and infra is None and any(
        r.stop_reason == "infrastructure-cancelled" for r in evidence.roles))

    def infrastructure_precedes(at: float | None) -> bool:
        return infra_unknown or (infra is not None and (at is None or at >= infra))

    def deadline(at: float, *, witnessed: bool = False) -> None:
        if (at > plan.deadline or witnessed) and not infrastructure_precedes(at):
            failures.add("deadline")

    if evidence is None:
        unknown.add("wave-not-observed")
        observed: dict[str, RoleEvidence] = {}
    else:
        if infra is not None:
            unknown.add("infrastructure-failure")
            if not _number(infra):
                unknown.add("invalid-infrastructure-time")
                infra = None
                infra_unknown = True
        if infra_unknown:
            unknown.add("infrastructure-failure-time-unobserved")
        if evidence.cleanup_confirmed is not True:
            unknown.add("wave-cleanup-unconfirmed")
        if evidence.completion_elapsed is None or not _number(evidence.completion_elapsed):
            unknown.add("completion-unobserved")
        if evidence.deadline_witnessed_at is not None:
            if not _number(evidence.deadline_witnessed_at) or evidence.deadline_witnessed_at < plan.deadline:
                unknown.add("invalid-deadline-observation")
            else:
                deadline(evidence.deadline_witnessed_at, witnessed=True)
        observed = {}
        duplicates = set()
        for role in evidence.roles:
            if role.role in observed:
                unknown.add("duplicate-role-capture")
                duplicates.add(role.role)
            observed[role.role] = role
        for role_name in duplicates:
            del observed[role_name]
        if set(observed) - {r.role for r in plan.roles}:
            unknown.add("undeclared-role-capture")

    for binding in plan.roles:
        name = binding.role
        r = observed.get(name)
        record: dict[str, Any] = {"role": name, "attempt_id": binding.attempt_id,
            "session_id": binding.session_id, "transcript_sha256": None, "protocol_sha256": None,
            "artifacts": None, "pokes": None, "tokens": None, "wall_seconds": None,
            "started": False, "stop_reason": None}
        diagnostics[name] = record
        if r is None:
            unknown.add(f"{name}:role-not-observed")
            continue
        if (r.attempt_id != binding.attempt_id or r.session_id != binding.session_id
                or binding.session_id is None):
            unknown.add(f"{name}:session-capture-binding")
            continue
        record.update(started=r.started, stop_reason=r.stop_reason)
        if r.started is not True:
            unknown.add(f"{name}:non-start")
            continue
        if (r.stopped is not True or r.cleanup_confirmed is not True or r.capture_complete is not True
                or r.stop_reason in {"launch-failed", "infrastructure-cancelled", "operator-cancelled"}):
            unknown.add(f"{name}:infrastructure-unavailable")
        if r.stop_reason not in {"exited", "deadline", "launch-failed", "infrastructure-cancelled", "operator-cancelled"}:
            unknown.add(f"{name}:unknown-stop-reason")
        natural_exit = r.stop_reason == "exited" and not infrastructure_precedes(r.stop_elapsed)
        if r.stop_elapsed is not None and not _number(r.stop_elapsed):
            unknown.add(f"{name}:invalid-stop-time")
            natural_exit = False
        if natural_exit and type(r.exit_code) is int and r.exit_code != 0:
            failures.add(f"{name}:participant-exit")
        if r.stop_reason == "exited" and type(r.exit_code) is not int:
            unknown.add(f"{name}:exit-unobserved")
        # A role stop reason alone lacks a common-clock witness.
        if r.stop_reason == "deadline" and (evidence is None or evidence.deadline_witnessed_at is None):
            unknown.add(f"{name}:deadline-unobserved")
        p = r.pokes
        if (p is None or p.role != name or p.session_id != binding.session_id
                or type(p.pokes) is not int or p.pokes < 0):
            unknown.add(f"{name}:pokes-unobserved")
        else:
            record["pokes"] = p.pokes
        if r.tokens is not None:
            if type(r.tokens) is not int or r.tokens < 0:
                unknown.add(f"{name}:invalid-token-observation")
            else:
                record["tokens"] = r.tokens
        if r.wall_seconds is not None:
            if not _number(r.wall_seconds):
                unknown.add(f"{name}:invalid-wall-observation")
            else:
                record["wall_seconds"] = r.wall_seconds
        try:
            transcript = _jsonl(r.transcript)
            first = transcript[0]
            if first.get("type") != "session_meta" or first.get("payload", {}).get("id") != binding.session_id:
                raise ValueError("transcript session differs")
            if any(row.get("payload", {}).get("id") != binding.session_id
                   for row in transcript if row.get("type") == "session_meta"):
                raise ValueError("transcript session changed")
            record["transcript_sha256"] = r.transcript.sha256 if r.transcript else None
        except (ValueError, TypeError, AttributeError, UnicodeError):
            unknown.add(f"{name}:transcript-unavailable")
        try:
            rows = _jsonl(r.protocol)
            record["protocol_sha256"] = r.protocol.sha256 if r.protocol else None
            acknowledged = completed = False
            last = -1.0
            expected = {"wave_id": plan.wave_id, "role": name, "attempt_id": binding.attempt_id,
                "session_id": binding.session_id, "task": binding.task, "generation": binding.generation,
                "revision": binding.revision, "nonce": binding.nonce}
            for event in rows:
                if set(event) != set(expected) | {"op", "elapsed"} or not _number(event["elapsed"]):
                    raise ValueError("invalid protocol capture schema")
                if event["elapsed"] < last:
                    raise ValueError("unordered observation stream")
                last = event["elapsed"]
                last_event = max(last_event, last)
                if any(type(event[k]) is not type(v) or event[k] != v for k, v in expected.items()):
                    failures.add(f"{name}:wrong-assignment-identity")
                    continue
                deadline(event["elapsed"])
                if event["op"] == "ack":
                    if acknowledged or completed:
                        failures.add(f"{name}:duplicate-acknowledgement")
                    acknowledged = True
                elif event["op"] == "complete":
                    if completed or not acknowledged:
                        failures.add(f"{name}:duplicate-or-unacknowledged-completion")
                    completed = True
                else:
                    failures.add(f"{name}:invalid-operation")
            # Only a fully observed natural exit establishes abandonment.
            if (not acknowledged or not completed) and r.capture_complete is True and natural_exit:
                failures.add(f"{name}:unfinished-role")
        except (ValueError, TypeError, KeyError, UnicodeError):
            unknown.add(f"{name}:protocol-unavailable")
        if r.artifacts is None or r.capture_complete is not True:
            unknown.add(f"{name}:artifacts-unavailable")
        elif any(not blob.valid() for blob in r.artifacts.values()):
            unknown.add(f"{name}:artifact-corruption")
        else:
            record["artifacts"] = {path: blob.sha256 for path, blob in r.artifacts.items()}
            artifacts[name] = {path: blob.data for path, blob in r.artifacts.items()}
            if set(binding.required_artifacts) - set(r.artifacts):
                if natural_exit:
                    failures.add(f"{name}:missing-required-artifact")
                else:
                    unknown.add(f"{name}:artifacts-incomplete")

    delivery: DeliveryGrade | None = None
    if (evidence is not None and evidence.wave_id == plan.wave_id
            and len(artifacts) == len(plan.roles) and all(
                set(r.required_artifacts) <= set(artifacts[r.role]) for r in plan.roles)):
        try:
            delivery = grade(plan, artifacts)
            if not isinstance(delivery, DeliveryGrade):
                raise TypeError("invalid grader record")
            if delivery.completed_elapsed is None or not _number(delivery.completed_elapsed):
                unknown.add("delivery-grading-time-unobserved")
            else:
                deadline(delivery.completed_elapsed)
                if delivery.completed_elapsed < last_event:
                    unknown.add("grading-before-observed-completion")
            if delivery.status == "FAIL":
                if infrastructure_precedes(delivery.completed_elapsed):
                    unknown.add("delivery-interrupted-by-infrastructure")
                else:
                    failures.add("incorrect-integrated-delivery")
            elif delivery.status == "UNKNOWN":
                unknown.add("delivery-grading-unavailable")
            elif delivery.status != "PASS":
                raise ValueError("invalid grader verdict")
        except (OSError, ValueError, TypeError, RuntimeError):
            delivery = None
            unknown.add("delivery-grading-unavailable")
    else:
        unknown.add("delivery-unobserved")
    if evidence and not unknown and evidence.completion_elapsed is not None:
        deadline(evidence.completion_elapsed)
    if evidence and _number(evidence.completion_elapsed) and evidence.completion_elapsed < last_event:
        unknown.add("capture-completion-time-disagrees")
    handoffs = dict(evidence.handoff_timings) if evidence and evidence.handoff_timings is not None else None
    clutter = evidence.clutter_count if evidence else None
    if handoffs is not None and any(not _number(v) for v in handoffs.values()):
        unknown.add("invalid-handoff-observation")
        handoffs = None
    if clutter is not None and (type(clutter) is not int or clutter < 0):
        unknown.add("invalid-clutter-observation")
        clutter = None
    status: Verdict = "FAIL" if failures else "UNKNOWN" if unknown else "PASS"
    elapsed = evidence.completion_elapsed if evidence and _number(evidence.completion_elapsed) else None
    if delivery and delivery.completed_elapsed is not None and _number(delivery.completed_elapsed):
        elapsed = max(elapsed, delivery.completed_elapsed) if elapsed is not None else delivery.completed_elapsed
    token_values = [r["tokens"] for r in diagnostics.values()]
    return {"version": 1, "wave_id": plan.wave_id, "status": status,
        "primary": {"unit": "wave", "planned": 1, "completed": int(status == "PASS")},
        "failures": sorted(failures), "unknown": sorted(unknown), "roles": diagnostics,
        "deadline": plan.deadline, "completion_elapsed": elapsed,
        "delivery": {"status": delivery.status, "completed_elapsed": delivery.completed_elapsed,
            "reasons": list(delivery.reasons)} if delivery else None,
        "metrics": {"timeout": (evidence.deadline_witnessed_at is not None or any(
                r.stop_reason == "deadline" for r in evidence.roles)) if evidence else None,
            "tokens": sum(token_values) if all(v is not None for v in token_values) else None,
            "wall_seconds": elapsed,
            "abandonment": evidence.abandonment if evidence else None,
            "handoff_timings": handoffs, "clutter_count": clutter},
        "deadline_scope": "through-capture-grading-and-confirmed-cleanup",
        "final_decision_emission": "outside-completion-deadline"}


def report(plans: Sequence[WavePlan], evidence: Mapping[str, WaveEvidence], grade: ArtifactGrader) -> dict[str, Any]:
    """Reconcile the declared denominator, never the successfully launched subset."""
    ids = [p.wave_id for p in plans]
    if not ids or len(set(ids)) != len(ids) or set(evidence) - set(ids):
        raise ValueError("planned wave population must be nonempty, unique and closed")
    waves = [verdict(p, evidence.get(p.wave_id), grade) for p in plans]
    return {"version": 1, "primary": {"unit": "wave", "planned": len(plans),
        "completed": sum(w["status"] == "PASS" for w in waves),
        **{s.lower(): sum(w["status"] == s for w in waves) for s in ("PASS", "FAIL", "UNKNOWN")}}, "waves": waves}
