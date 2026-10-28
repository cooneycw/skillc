"""Attempt-local resume-state admission (#536); caller serializes completion.

The verified profile supplies a protocol and identity. Filesystem equality never
supplies stage success: carried rows require earlier controller facts. No writer
identity, candidate quiescence, or whole-stream authenticity is established.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from . import stage_capture

MAX_BYTES = 64 * 1024 * 1024
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
SHA = re.compile(r"sha256:[0-9a-f]{64}\Z")
REASONS = frozenset({"no-selected-state", "no-save", "not-observed", "selection-unreadable",
                     "input-unreadable", "parse-failed", "serialization-failed", "write-failed",
                     "short-write", "cleanup-failed", "presence-unreadable", "unsafe-logical-id", "size-limit"})


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def configuration(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"version", "family", "plan", "operations", "state_path"}:
        raise ValueError("gate-state protocol fields are unsupported")
    if (type(value["version"]) is not int or value["version"] != 1
            or not isinstance(value["family"], str) or not ID.fullmatch(value["family"])):
        raise ValueError("gate-state protocol version/family is unsupported")
    if not isinstance(value["plan"], str) or not ID.fullmatch(value["plan"]):
        raise ValueError("gate-state plan is unsafe")
    path = value["state_path"]
    if (not isinstance(path, str) or len(path) > 133 or len(path.split("/")) != 2
            or path.split("/")[0] != ".git" or not FILE.fullmatch(path.split("/")[1])):
        raise ValueError("gate-state state_path must be one safe directory below .git")
    operations = value["operations"]
    if (not isinstance(operations, dict) or not 1 <= len(operations) <= 16
            or any(not isinstance(k, str) or not ID.fullmatch(k) or v not in ("runner", "inspection")
                   for k, v in operations.items()) or "runner" not in operations.values()):
        raise ValueError("gate-state operations are unsupported")
    if value["plan"] != "check" or operations != {
            "flow-check-plan": "runner", "flow-check-summary": "inspection"}:
        raise ValueError("gate-state operation/plan is unsupported by this fixture protocol")
    return copy.deepcopy(value)


@dataclass(frozen=True)
class Protocol:
    family: str
    state_path: str
    plan: str
    operations: tuple[tuple[str, str], ...]
    profile_digest: str
    inventory_digest: str
    producer_revision: str

    @classmethod
    def from_inventory(cls, inventory: Mapping[str, Any]) -> Protocol:
        """Bind only AFTER the caller revalidates and matches the live closure."""
        cfg = configuration(inventory.get("gate_state_protocol"))
        profile = inventory.get("profile_digest")
        subject = inventory.get("subject")
        revision = subject.get("revision") if isinstance(subject, dict) else None
        if not isinstance(profile, str) or not SHA.fullmatch(profile) or not isinstance(revision, str) \
                or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("gate-state profile/producer identity is missing")
        return cls(family=cfg["family"], state_path=cfg["state_path"], plan=cfg["plan"],
                   operations=tuple(sorted(cfg["operations"].items())), profile_digest=profile,
                   inventory_digest=digest(canonical(inventory)), producer_revision=revision)

    @property
    def identity(self) -> str:
        return digest(canonical([self.profile_digest, self.inventory_digest, self.producer_revision,
                                 self.family, self.state_path, self.plan, self.operations]))


@dataclass(frozen=True)
class Identity:
    file: str
    sha256: str
    bytes: int

    def json(self) -> dict[str, object]:
        return {"file": self.file, "sha256": self.sha256, "bytes": self.bytes}


@dataclass(frozen=True)
class Snapshot:
    repository: str | None
    source: str | None
    files: Mapping[str, Identity]
    reason: str | None = None

    @property
    def complete(self) -> bool:
        return (self.reason is None and isinstance(self.repository, str) and bool(self.repository)
                and isinstance(self.source, str) and SHA.fullmatch(self.source) is not None)

    def json(self) -> dict[str, object]:
        return {"coverage": "complete" if self.complete else "unreadable", "reason": self.reason,
                "repository": self.repository, "source": self.source,
                "files": [self.files[k].json() for k in sorted(self.files)] if self.complete else None}


def snapshot(root: Path, paths: Sequence[str], *, repository: str, source: str) -> Snapshot:
    """Bounded controller-export reader. No raw state leaves this function."""
    def bad() -> Snapshot:
        return Snapshot(repository, source, {}, "state-export-unreadable")
    if len(paths) != 1 or root.is_symlink():
        return bad()
    rel = Path(paths[0])
    if rel.is_absolute() or not rel.parts or any(p in (".", "..") for p in rel.parts):
        return bad()
    target = root
    try:
        for part in rel.parts:
            target /= part
            try:
                info = target.lstat()
            except FileNotFoundError:
                return Snapshot(repository, source, {})
            if not stat.S_ISDIR(info.st_mode):
                return bad()
        entries = []
        for entry in target.iterdir():
            entries.append(entry)
            if len(entries) > 1:
                return bad()
        files = {}
        for entry in entries:
            if not FILE.fullmatch(entry.name) or not hasattr(os, "O_NOFOLLOW"):
                return bad()
            fd = os.open(entry, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
                    return bad()
                raw = stream.read(MAX_BYTES + 1)
                after = os.fstat(stream.fileno())
            if len(raw) > MAX_BYTES or len(raw) != before.st_size \
                    or (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                return bad()
            files[entry.name] = Identity(entry.name, digest(raw), len(raw))
        return Snapshot(repository, source, files)
    except (OSError, ValueError):
        return bad()


def _identity(value: object, kind: str) -> tuple[str, Identity | None]:
    if not isinstance(value, dict) or set(value) != {"status", "file", "sha256", "bytes", "reason"}:
        raise ValueError("identity-shape")
    status = value["status"]
    if status == kind:
        if (not isinstance(value["file"], str) or not FILE.fullmatch(value["file"])
                or not isinstance(value["sha256"], str) or not SHA.fullmatch(value["sha256"])
                or type(value["bytes"]) is not int or not 0 <= value["bytes"] <= MAX_BYTES
                or value["reason"] is not None):
            raise ValueError("identity-data")
        return str(status), Identity(value["file"], value["sha256"], value["bytes"])
    if status not in ("none", "unreadable") or any(value[k] is not None for k in ("file", "sha256", "bytes")):
        raise ValueError("identity-status")
    expected = "no-selected-state" if kind == "loaded" else "no-save"
    if (status == "none" and value["reason"] != expected) or not isinstance(value["reason"], str) or value["reason"] not in REASONS:
        raise ValueError("identity-reason")
    return str(status), None


def metadata(value: object, plan: str, family: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"version", "family", "plan", "consumed", "generated", "final_state"}:
        raise ValueError("metadata-shape")
    if type(value["version"]) is not int or value["version"] != 1 \
            or value["family"] != family or value["plan"] != plan:
        raise ValueError("metadata-version-family-plan")
    _identity(value["consumed"], "loaded")
    _identity(value["generated"], "written")
    final = value["final_state"]
    if not isinstance(final, dict) or set(final) != {"status", "reason"}:
        raise ValueError("final-shape")
    if final["status"] not in ("present", "absent", "unreadable"):
        raise ValueError("final-status")
    if (final["status"] != "unreadable" and final["reason"] is not None) \
            or (final["status"] == "unreadable" and (not isinstance(final["reason"], str) or final["reason"] not in REASONS)):
        raise ValueError("final-reason")
    return copy.deepcopy(value)


@dataclass(frozen=True)
class Execution:
    sequence: int
    cwd: str | None
    before: Snapshot
    key: tuple[str, ...] | None


@dataclass(frozen=True)
class Lease:
    sequence: int
    identity: Identity
    facts: Mapping[str, dict[str, object]]
    generation: int


class Ledger:
    """One trusted witness/attempt. All methods run under its execution lock."""

    def __init__(self, protocol: Protocol, attempt_id: str) -> None:
        self.protocol = protocol
        self.attempt_id = attempt_id
        self.sequence = 0
        self.leases: dict[tuple[str, ...], Lease] = {}
        self.seen: set[str] = set()

    def begin(self, cwd: str | None, before: Snapshot) -> Execution:
        self.sequence += 1
        key = ((self.attempt_id, str(before.repository), str(cwd), str(before.source), self.protocol.identity,
                self.protocol.family, self.protocol.plan) if before.complete else None)
        return Execution(self.sequence, cwd, before, key)

    def invalidate(self, key: tuple[str, ...] | None, sequence: int) -> None:
        for candidate in list(self.leases):
            if (key is None or key[:2] == candidate[:2]) and self.leases[candidate].generation <= sequence:
                del self.leases[candidate]

    def finish(self, execution: Execution, gate: str, result: Any, retained: Mapping[str, Any],
               after: Snapshot, capture: Mapping[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, object]]:
        before, key, seq = execution.before, execution.key, execution.sequence
        evidence: dict[str, object] = {"execution_sequence": seq, "profile_inventory": self.protocol.inventory_digest,
                                      "producer_revision": self.protocol.producer_revision,
                                      "before": before.json(), "after": after.json(), "admission": "refused"}

        def refuse(reason: str) -> tuple[dict[str, Any], dict[str, object]]:
            self.invalidate(key, seq)
            evidence["reason"] = reason
            return stage_capture.unavailable(reason), evidence

        if seq != self.sequence:
            return refuse("stale-execution")
        if (result.reason != "exited" or type(result.exit_code) is not int
                or result.stop_confirmed not in (None, True) or result.stop_confirmed is False
                or type(result.stop_confirmed) not in (type(None), bool)
                or any(not isinstance(retained.get(s), Mapping) or retained[s].get("coverage") != "complete"
                       for s in ("stdout", "stderr"))):
            return refuse("incomplete-execution-or-retention")
        for stream in ("stdout", "stderr"):
            raw = getattr(result, stream)
            if (not isinstance(raw, bytes) or retained[stream].get("digest") != digest(raw)
                    or retained[stream].get("size") != len(raw)
                    or getattr(result, stream + "_truncated") or getattr(result, stream + "_incomplete")):
                return refuse("incomplete-execution-or-retention")
        if not isinstance(execution.cwd, str) or not execution.cwd:
            return refuse("cwd-unavailable")
        if not before.complete or not after.complete or before.repository != after.repository or before.source != after.source:
            return refuse("state-or-source-export-unavailable")
        assert key is not None
        prior = self.leases.get(key)
        operation = dict(self.protocol.operations).get(gate)
        if operation == "inspection":
            try:
                lines = [line for line in result.stdout.decode("utf-8").splitlines() if line.strip()]
            except UnicodeError:
                return refuse("inspection-output-unavailable")
            if (result.exit_code != 0 or not lines or lines[-1] != "FLOW_FINISH_GATE: ok"
                    or sum(line.startswith("FLOW_FINISH_GATE:") for line in lines) != 1):
                return refuse("inspection-verdict-unavailable")
            if prior is not None and before.files == after.files == {prior.identity.file: prior.identity}:
                self.leases[key] = replace(prior, generation=seq)
                evidence.update(admission="preserved", predecessor=prior.sequence)
                return None, evidence
            self.invalidate(key, seq)
            evidence.update(admission="absent" if not before.files and not after.files else "refused",
                            reason="inspection-earns-no-facts")
            return None, evidence
        if operation != "runner" or capture is None or capture.get("status") != "captured":
            return refuse("runner-stage-capture-unavailable")
        try:
            document, _verdict, why = stage_capture._document(result.stdout.decode("utf-8"), strict=True)
            if document is None or why is not None:
                return refuse("runner-document-unavailable")
            meta = metadata(document.get("resume_state_evidence"), self.protocol.plan, self.protocol.family)
            consumed_status, consumed = _identity(meta["consumed"], "loaded")
            generated_status, generated = _identity(meta["generated"], "written")
            run_id = document.get("run_id")
            if (not isinstance(run_id, str) or not ID.fullmatch(run_id)
                    or not re.fullmatch(re.escape(self.protocol.plan) + r"-[0-9a-f]{8}", run_id)
                    or any(identity is not None and identity.file != run_id + ".json"
                           for identity in (consumed, generated))):
                return refuse("run-identity-disagrees")
            evidence["run_id"] = run_id
            evidence["producer"] = meta
            if consumed_status == "loaded":
                if prior is None or prior.sequence >= seq or consumed != prior.identity \
                        or before.files != {prior.identity.file: prior.identity}:
                    return refuse("no-matching-controller-predecessor")
            elif consumed_status != "none" or before.files:
                return refuse("unwitnessed-or-unreadable-input")
            if generated_status == "unreadable" or meta["final_state"]["status"] == "unreadable":
                return refuse("generated-or-final-state-unreadable")
            if meta["final_state"]["status"] == "absent":
                if after.files:
                    return refuse("cleanup-export-disagrees")
            else:
                expected = generated if generated is not None else consumed
                if expected is None or after.files != {expected.file: expected}:
                    return refuse("generated-export-disagrees")
            details = document.get("step_details")
            if not isinstance(details, list) or not 1 <= len(details) <= 256:
                return refuse("stage-population-unavailable")
            stages = copy.deepcopy(dict(capture))
            facts: dict[str, dict[str, object]] = {}
            all_carried = True
            for row in details:
                if (not isinstance(row, dict) or not isinstance(row.get("id"), str) or not ID.fullmatch(row["id"])
                        or any(flag in row and type(row[flag]) is not bool
                               for flag in ("carried_from_previous_run", "executed_in_this_run"))
                        or (row.get("carried_from_previous_run") is True and row.get("executed_in_this_run") is True)):
                    return refuse("stage-shape-unavailable")
                name = row["id"]
                record = stages["stages"][name]
                carried = row.get("carried_from_previous_run") is True or row.get("executed_in_this_run") is False
                all_carried = all_carried and carried
                if carried:
                    earlier = prior.facts.get(name) if prior is not None and consumed is not None else None
                    if earlier is not None and earlier["runner_status"] == row["status"]:
                        record.update(earlier)
                        record["reason"] = "inherited from controller execution " + str(earlier["origin_execution"])
                    else:
                        record.update(outcome=None, reason="no matching earlier controller stage")
                elif record["outcome"] is not None:
                    record["origin_execution"] = seq
                if record["outcome"] is not None:
                    facts[name] = copy.deepcopy(record)
            output_digest = retained["stdout"]["digest"]
            duplicate = output_digest in self.seen
            self.seen.add(output_digest)
            if generated_status == "none" or duplicate or all_carried:
                if not all_carried or prior is None:
                    return refuse("no-new-producer-execution")
                if after.files and before.files == after.files == {prior.identity.file: prior.identity}:
                    self.leases[key] = replace(prior, generation=seq)
                    evidence.update(admission="preserved", predecessor=prior.sequence)
                elif not after.files:
                    self.invalidate(key, seq)
                    evidence["admission"] = "absent"
                else:
                    return refuse("no-op-state-changed")
                return stages, evidence
            if generated is None:
                return refuse("no-generated-identity")
            if after.files:
                self.invalidate(key, seq)
                self.leases[key] = Lease(seq, generated, facts, seq)
                evidence["admission"] = "admitted"
            else:
                self.invalidate(key, seq)
                evidence["admission"] = "absent"
            evidence["predecessor"] = prior.sequence if prior is not None else None
            return stages, evidence
        except (ValueError, UnicodeError, KeyError, TypeError, AttributeError):
            return refuse("unsupported-runner-evidence")
